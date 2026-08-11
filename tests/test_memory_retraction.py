"""ADR-0002 RetractionReceipt: системный отзыв SILENT-фактов из Project Memory.

Покрывает:
- store.load_memory: фильтрация REFUTED, include_retracted, backward-compat
  (узлы без status = ACTIVE, legacy dict-формат);
- layer.intel_add_memory_node: status ACTIVE/VERIFIED, запрет REFUTED и
  невалидного статуса, миграция legacy dict-формата;
- layer.intel_retract_memory_node: причина обязательна, not found, повторный
  отзыв запрещён, lifecycle VERIFIED -> REFUTED;
- конкурентность: параллельные add/retract не теряют записи (TOCTOU, ADR-0002).

Изоляция: MSCODEBASE_DATA_DIR указывает во временный каталог (как в эксперименте
memory_contamination: assert store_dir != реальный).
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

import pytest

from src.core.intelligence.layer import ProjectIntelligenceLayer
from src.core.intelligence.store import IntelligenceStore

# =====================================================================
# FIXTURES
# =====================================================================


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch):
    """Изолирует <data_root> от реального: MSCODEBASE_DATA_DIR -> tmp_path."""
    data_root = tmp_path / "data_root"
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(data_root))
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    return project


def _make_layer(project: Path) -> ProjectIntelligenceLayer:
    """Layer без indexer/searcher — memory-методы их не используют."""
    return ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]


def _add(
    layer: ProjectIntelligenceLayer,
    section: str = "adrs",
    data: Optional[dict] = None,
    status: str = "ACTIVE",
) -> str:
    return asyncio.run(
        layer.intel_add_memory_node(
            section, json.dumps(data if data is not None else {"title": "x"}), status
        )
    )


def _retract(layer: ProjectIntelligenceLayer, node_id: str, reason: Optional[str]) -> str:
    return asyncio.run(layer.intel_retract_memory_node(node_id, reason or ""))


def _raw_nodes(layer: ProjectIntelligenceLayer):
    """Сырые узлы из файла (включая REFUTED)."""
    return layer.store._load_json("project_memory.json")


# =====================================================================
# STORE: ФИЛЬТРАЦИЯ ПРИ ЧТЕНИИ
# =====================================================================


def test_store_hides_refuted_keeps_active_verified_and_legacy(isolated_data: Path):
    store = IntelligenceStore(isolated_data)
    store._save_json(
        "project_memory.json",
        [
            {"node_id": "NODE-A", "section": "adrs", "timestamp": "t",
             "data": {"t": 1}, "status": "ACTIVE"},
            {"node_id": "NODE-B", "section": "adrs", "timestamp": "t",
             "data": {"t": 2}, "status": "VERIFIED"},
            {"node_id": "NODE-C", "section": "adrs", "timestamp": "t",
             "data": {"t": 3}, "status": "REFUTED"},
            # Legacy: без поля status -> ACTIVE (backward-compat, ADR-0002)
            {"node_id": "NODE-D", "section": "known_issues", "timestamp": "t",
             "data": {"t": 4}},
        ],
    )
    mem = store.load_memory()
    assert [n["node_id"] for n in mem["adrs"]] == ["NODE-A", "NODE-B"]
    assert [n["node_id"] for n in mem["known_issues"]] == ["NODE-D"]


def test_store_include_retracted_returns_refuted(isolated_data: Path):
    store = IntelligenceStore(isolated_data)
    store._save_json(
        "project_memory.json",
        [
            {"node_id": "NODE-C", "section": "adrs", "timestamp": "t",
             "data": {"t": 3}, "status": "REFUTED"},
        ],
    )
    assert store.load_memory()["adrs"] == []
    full = store.load_memory(include_retracted=True)
    assert [n["node_id"] for n in full["adrs"]] == ["NODE-C"]


def test_store_legacy_dict_format_intact(isolated_data: Path):
    store = IntelligenceStore(isolated_data)
    store._save_json("project_memory.json", {"adrs": [{"title": "old"}]})  # type: ignore[arg-type]
    mem = store.load_memory()
    assert len(mem["adrs"]) == 1
    assert mem["adrs"][0]["title"] == "old"


# =====================================================================
# LAYER: intel_add_memory_node — STATUS
# =====================================================================


def test_add_default_status_active(isolated_data: Path):
    layer = _make_layer(isolated_data)
    resp = _add(layer, data={"title": "t"})
    assert "NODE-" in resp and "ACTIVE" in resp
    nodes = _raw_nodes(layer)
    assert len(nodes) == 1 and nodes[0]["status"] == "ACTIVE"


def test_add_verified_status(isolated_data: Path):
    layer = _make_layer(isolated_data)
    resp = _add(layer, section="tech_debt", data={"d": 1}, status="VERIFIED")
    assert "VERIFIED" in resp
    nodes = _raw_nodes(layer)
    assert len(nodes) == 1 and nodes[0]["status"] == "VERIFIED"


def test_add_rejects_refuted_status(isolated_data: Path):
    layer = _make_layer(isolated_data)
    resp = _add(layer, data={"title": "x"}, status="REFUTED")
    assert "intel_retract_memory_node" in resp  # объясняет легитимный путь
    assert _raw_nodes(layer) == []


def test_add_rejects_invalid_status(isolated_data: Path):
    layer = _make_layer(isolated_data)
    resp = _add(layer, data={"title": "x"}, status="BOGUS")
    assert "BOGUS" in resp and "ACTIVE" in resp and "VERIFIED" in resp
    assert _raw_nodes(layer) == []


def test_add_migrates_legacy_dict_format(isolated_data: Path):
    layer = _make_layer(isolated_data)
    layer.store._save_json("project_memory.json", {"adrs": [{"title": "old"}]})  # type: ignore[arg-type]
    _add(layer, data={"title": "new"})
    nodes = _raw_nodes(layer)
    assert isinstance(nodes, list) and len(nodes) == 2
    # legacy-запись получила status=ACTIVE при миграции (ADR-0002)
    assert all(n.get("status") == "ACTIVE" for n in nodes)


# =====================================================================
# WRITE-TIME ANCHOR CAPTURE (ADR-0003, урок Exp 1-V)
# =====================================================================


def test_add_memory_node_captures_import_anchor(isolated_data: Path):
    """Проза-упоминание 'import X' -> точный якорь записан при записи узла."""
    layer = _make_layer(isolated_data)
    _add(layer, data={"claim": "транспорт использует import fastmcp"})
    node = _raw_nodes(layer)[0]
    anchors = node["data"].get("anchors", [])
    assert {"kind": "import", "value": "fastmcp"} in anchors


def test_add_memory_node_prose_no_anchors(isolated_data: Path):
    """Проза без артефакт-синтаксиса -> якорей нет (INCONCLUSIVE-семантика)."""
    layer = _make_layer(isolated_data)
    _add(layer, data={"claim": "предпочтение владельца без артефактов"})
    node = _raw_nodes(layer)[0]
    assert "anchors" not in node["data"]


def test_add_memory_node_preserves_explicit_anchors(isolated_data: Path):
    """Явные data.anchors сохраняются (мердж с извлечёнными)."""
    layer = _make_layer(isolated_data)
    _add(layer, data={"claim": "x", "anchors": [{"kind": "env", "value": "FOO_BAR"}]})
    node = _raw_nodes(layer)[0]
    anchors = node["data"].get("anchors", [])
    assert {"kind": "env", "value": "FOO_BAR"} in anchors


def test_add_memory_node_skips_absolute_path(isolated_data: Path):
    """Абсолютный путь (C:\\Users) не становится файловым якорем (ADR-0003)."""
    layer = _make_layer(isolated_data)
    _add(layer, data={"claim": "данные в C:\\Users\\misha\\graph.db"})
    node = _raw_nodes(layer)[0]
    anchors = node["data"].get("anchors", [])
    assert not any(a["kind"] == "file" for a in anchors)


# =====================================================================
# LAYER: intel_retract_memory_node
# =====================================================================


def test_retract_requires_nonempty_reason(isolated_data: Path):
    layer = _make_layer(isolated_data)
    _add(layer)
    node_id = _raw_nodes(layer)[0]["node_id"]
    for bad in ("", "   ", None):
        resp = _retract(layer, node_id, bad)
        assert "reason" in resp.lower() or "причин" in resp
    assert _raw_nodes(layer)[0]["status"] == "ACTIVE"


def test_retract_unknown_node(isolated_data: Path):
    layer = _make_layer(isolated_data)
    resp = _retract(layer, "NODE-NOPE", "test")
    assert "не найден" in resp


def test_retract_active_node_lifecycle(isolated_data: Path):
    layer = _make_layer(isolated_data)
    _add(layer, data={"title": "bad"})
    node_id = _raw_nodes(layer)[0]["node_id"]

    resp = _retract(layer, node_id, "SILENT-факт: код молчит")
    assert "REFUTED" in resp

    # Скрыт по умолчанию...
    assert layer.store.load_memory()["adrs"] == []
    # ...но сохранён с причиной и временем для аудита
    full = layer.store.load_memory(include_retracted=True)["adrs"]
    assert len(full) == 1
    n = full[0]
    assert n["status"] == "REFUTED"
    assert n["retract_reason"] == "SILENT-факт: код молчит"
    assert "retracted_at" in n


def test_retract_verified_node_owp_lifecycle(isolated_data: Path):
    """OWP lifecycle: VERIFIED -> REFUTED (не только ACTIVE -> REFUTED)."""
    layer = _make_layer(isolated_data)
    _add(layer, data={"title": "checked"}, status="VERIFIED")
    node_id = _raw_nodes(layer)[0]["node_id"]
    assert _raw_nodes(layer)[0]["status"] == "VERIFIED"

    _retract(layer, node_id, "проверка против кода опровергла факт")
    n = layer.store.load_memory(include_retracted=True)["adrs"][0]
    assert n["status"] == "REFUTED"
    assert n["retract_reason"] == "проверка против кода опровергла факт"


def test_retract_twice_rejected(isolated_data: Path):
    layer = _make_layer(isolated_data)
    _add(layer)
    node_id = _raw_nodes(layer)[0]["node_id"]
    _retract(layer, node_id, "первая причина")
    resp = _retract(layer, node_id, "вторая причина")
    assert "уже отозван" in resp
    # Первичная причина сохраняется — «переписать историю» нельзя
    n = layer.store.load_memory(include_retracted=True)["adrs"][0]
    assert n["retract_reason"] == "первая причина"


# =====================================================================
# CONCURRENCY (ADR-0002 §5.13): add + retract под одним локом
# =====================================================================


def test_concurrent_add_and_retract_no_lost_updates(isolated_data: Path):
    layer = _make_layer(isolated_data)

    async def _run():
        await asyncio.gather(
            *[
                layer.intel_add_memory_node("adrs", json.dumps({"i": i}))
                for i in range(15)
            ]
        )
        nodes = _raw_nodes(layer)
        assert len(nodes) == 15, "потерянные аппенды при конкурентной записи"
        target = nodes[0]["node_id"]
        await layer.intel_retract_memory_node(target, "конкурентный отзыв")
        return target

    target = asyncio.run(_run())

    visible = layer.store.load_memory()["adrs"]
    assert len(visible) == 14
    assert all(n["node_id"] != target for n in visible)

    full = layer.store.load_memory(include_retracted=True)["adrs"]
    assert len(full) == 15
    retracted = [n for n in full if n["node_id"] == target][0]
    assert retracted["status"] == "REFUTED"
    assert retracted["retract_reason"] == "конкурентный отзыв"
