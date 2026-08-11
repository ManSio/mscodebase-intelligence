"""ADR-0003 Verify-On-Read: ленивая валидация ACTIVE-узлов при извлечении.

Покрывает:
- extract_anchors: file:/import/env/пути из data.anchors и текста claim (лёгкий regex);
- вердикты: FOUND -> VERIFIED, NOT_FOUND -> REFUTED (SILENT_ABSENCE_ON_READ +
  проваленный якорь + retract_source), INCONCLUSIVE (нет якорей) -> ACTIVE;
- кэш по hash(node_id + HEAD): второй прогон на том же HEAD — cache hit, проверок 0;
- смена HEAD -> per-node инвалидация (повторная проверка);
- бюджет латентности: превышение -> необработанные узлы остаются как есть
  (graceful degradation);
- хук в intel_get_project_memory: verify_on_read=True по умолчанию, False — отключение.

Изоляция: MSCODEBASE_DATA_DIR -> tmp; проект с мини-деревом src + .env.
"""

import asyncio
import json
import threading
from pathlib import Path

import pytest

from src.core.intelligence.layer import ProjectIntelligenceLayer
from src.core.intelligence.store import IntelligenceStore
from src.core.intelligence.verify_on_read import (
    REASON_SILENT_ABSENCE,
    RETRACT_SOURCE,
    STATUS_ACTIVE,
    STATUS_REFUTED,
    STATUS_VERIFIED,
    VerifyOnRead,
    extract_anchors,
)

SRC_MAIN = "import fastmcp\nimport sqlite3\n\nprint('ok')\n"
ENV_FILE = "LLAMA_CPP_ENABLED=true\nMSCODEBASE_EXECUTE_SCRIPT_ENABLED=false\n"


# =====================================================================
# FIXTURES
# =====================================================================


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    """Изолированный проект: MSCODEBASE_DATA_DIR -> tmp, src-дерево, .env."""
    data_root = tmp_path / "data_root"
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(data_root))
    proj = tmp_path / "project"
    src = proj / "src"
    (src / "core").mkdir(parents=True, exist_ok=True)
    (src / "main.py").write_text(SRC_MAIN, encoding="utf-8")
    (src / "core" / "cypher_engine.py").write_text("class CypherEngine: pass\n", encoding="utf-8")
    (proj / ".env").write_text(ENV_FILE, encoding="utf-8")
    (proj / ".env.example").write_text(ENV_FILE, encoding="utf-8")
    return proj


def _node(node_id: str, claim: str, anchors=None, status: str = STATUS_ACTIVE) -> dict:
    data = {"claim": claim}
    if anchors is not None:
        data["anchors"] = anchors
    n = {
        "node_id": node_id,
        "section": "adrs",
        "timestamp": "2026-08-11 12:00:00",
        "data": data,
    }
    if status != STATUS_ACTIVE:
        n["status"] = status
    return n


def _seed(store: IntelligenceStore, nodes: list) -> None:
    store.save_memory(nodes)


def _make_verifier(project: Path, store: IntelligenceStore, lock=None) -> VerifyOnRead:
    return VerifyOnRead(project, store, lock or threading.Lock())


# =====================================================================
# ANCHOR EXTRACTION
# =====================================================================


def test_extract_anchors_from_data_anchors():
    node = _node(
        "N1", "claim",
        anchors=[
            {"kind": "file", "value": "src/core/cypher_engine.py"},
            {"kind": "import", "value": "fastmcp"},
            {"kind": "env", "value": "LLAMA_CPP_ENABLED"},
        ],
    )
    anchors = extract_anchors(node)
    kinds = {(a.kind, a.value) for a in anchors}
    assert ("file", "src/core/cypher_engine.py") in kinds
    assert ("import", "fastmcp") in kinds
    assert ("env", "LLAMA_CPP_ENABLED") in kinds


def test_extract_anchors_from_text_syntax():
    """Синтаксис в тексте claim: file:, import X, env:KEY, путь с разделителем."""
    node = _node(
        "N1",
        "код использует file:src/core/cypher_engine.py; import fastmcp; env:LLAMA_CPP_ENABLED; src/conf/app.json",
    )
    anchors = extract_anchors(node)
    kinds = {(a.kind, a.value) for a in anchors}
    assert ("file", "src/core/cypher_engine.py") in kinds
    assert ("import", "fastmcp") in kinds
    assert ("env", "LLAMA_CPP_ENABLED") in kinds
    assert ("file", "src/conf/app.json") in kinds


def test_extract_anchors_no_anchors():
    node = _node("N1", "простое утверждение о внешнем окружении без якорей")
    assert extract_anchors(node) == []


# =====================================================================
# VERDICTS
# =====================================================================


def test_found_anchor_verified_included(project: Path):
    store = IntelligenceStore(project)
    _seed(store, [_node("N1", "использует fastmcp", anchors=[{"kind": "import", "value": "fastmcp"}])])
    verifier = _make_verifier(project, store)

    memory, stats = verifier.run(store.load_memory())
    assert [n["node_id"] for n in memory["adrs"]] == ["N1"]
    assert stats["verified"] == 1 and stats["refuted"] == 0
    raw = store._load_json("project_memory.json")[0]
    assert raw["status"] == STATUS_VERIFIED
    assert "verified_at" in raw


def test_not_found_anchor_refuted_excluded(project: Path):
    store = IntelligenceStore(project)
    _seed(store, [_node("N2", "использует grafana", anchors=[{"kind": "import", "value": "grafana"}])])
    verifier = _make_verifier(project, store)

    memory, stats = verifier.run(store.load_memory())
    assert memory["adrs"] == []  # отсечён до формирования контекста
    assert stats["refuted"] == 1
    raw = store._load_json("project_memory.json")[0]
    assert raw["status"] == STATUS_REFUTED
    assert raw["retract_reason"] == f"{REASON_SILENT_ABSENCE}: import:grafana"
    assert raw["retract_source"] == RETRACT_SOURCE
    assert "retracted_at" in raw
    # Аудит: виден только с include_retracted
    assert store.load_memory()["adrs"] == []
    assert len(store.load_memory(include_retracted=True)["adrs"]) == 1


def test_no_anchors_inconclusive_stays_active(project: Path):
    store = IntelligenceStore(project)
    _seed(store, [_node("N3", "предпочтение владельца без следов в коде")])
    verifier = _make_verifier(project, store)

    memory, stats = verifier.run(store.load_memory())
    assert [n["node_id"] for n in memory["adrs"]] == ["N3"]
    assert stats["inconclusive"] == 1
    raw = store._load_json("project_memory.json")[0]
    assert raw.get("status", STATUS_ACTIVE) == STATUS_ACTIVE  # без авто-вердикта
    assert "verified_at" not in raw and "retracted_at" not in raw


def test_legacy_node_no_status_checkable_verified(project: Path):
    """Легаси-узел без поля status интерпретируется как ACTIVE (ADR-0002)."""
    store = IntelligenceStore(project)
    legacy = _node("N4", "использует sqlite3", anchors=[{"kind": "import", "value": "sqlite3"}])
    legacy.pop("status", None)
    _seed(store, [legacy])
    verifier = _make_verifier(project, store)

    memory, _ = verifier.run(store.load_memory())
    assert [n["node_id"] for n in memory["adrs"]] == ["N4"]
    assert store._load_json("project_memory.json")[0]["status"] == STATUS_VERIFIED


def test_env_anchor_found_and_absent(project: Path):
    store = IntelligenceStore(project)
    _seed(
        store,
        [
            _node("N5", "env есть", anchors=[{"kind": "env", "value": "LLAMA_CPP_ENABLED"}]),
            _node("N6", "env нет", anchors=[{"kind": "env", "value": "NO_SUCH_KEY_XYZ"}]),
        ],
    )
    verifier = _make_verifier(project, store)
    memory, stats = verifier.run(store.load_memory())
    assert [n["node_id"] for n in memory["adrs"]] == ["N5"]
    assert stats["verified"] == 1 and stats["refuted"] == 1
    raw = {n["node_id"]: n for n in store._load_json("project_memory.json")}
    assert raw["N6"]["retract_reason"] == f"{REASON_SILENT_ABSENCE}: env:NO_SUCH_KEY_XYZ"


def test_file_anchor_found(project: Path):
    store = IntelligenceStore(project)
    _seed(store, [_node("N7", "файл", anchors=[{"kind": "file", "value": "src/core/cypher_engine.py"}])])
    verifier = _make_verifier(project, store)
    memory, _ = verifier.run(store.load_memory())
    assert [n["node_id"] for n in memory["adrs"]] == ["N7"]
    assert store._load_json("project_memory.json")[0]["status"] == STATUS_VERIFIED


# =====================================================================
# CACHE (Q2: hash(node_id + HEAD), per-node инвалидация)
# =====================================================================


def test_cache_hit_second_run_same_head(project: Path):
    store = IntelligenceStore(project)
    _seed(
        store,
        [
            _node("N1", "a", anchors=[{"kind": "import", "value": "fastmcp"}]),
            _node("N2", "b", anchors=[{"kind": "import", "value": "fastmcp"}]),
        ],
    )
    verifier = _make_verifier(project, store)
    _, stats1 = verifier.run(store.load_memory())
    assert stats1["checked"] == 2

    _, stats2 = verifier.run(store.load_memory())  # тот же HEAD
    assert stats2["checked"] == 0  # неизменившийся репозиторий не перепроверяется
    assert stats2["cache_hits"] == stats2["nodes_seen"]
    assert stats2["nodes_seen"] == 2


def test_head_change_rechecks_per_node(project: Path):
    store = IntelligenceStore(project)
    _seed(store, [_node("N1", "a", anchors=[{"kind": "import", "value": "fastmcp"}])])
    verifier = _make_verifier(project, store)
    _, stats1 = verifier.run(store.load_memory())
    assert stats1["checked"] == 1

    # Сдвиг HEAD -> кэш для ЭТОЙ ноды естественно инвалидирован (ключ = node_id+sha)
    verifier._resolve_head = lambda: "NEW-HEAD-abc123"
    _, stats2 = verifier.run(store.load_memory())
    assert stats2["checked"] == 1
    assert stats2["cache_hits"] == 0


def test_verified_node_rechecked_on_head_change(project: Path):
    """Q2: VERIFIED не «липкий» — на новом HEAD узел перепроверяется."""
    store = IntelligenceStore(project)
    _seed(store, [_node("N1", "a", anchors=[{"kind": "import", "value": "fastmcp"}])])
    verifier = _make_verifier(project, store)
    _, stats1 = verifier.run(store.load_memory())
    assert stats1["verified"] == 1

    verifier._resolve_head = lambda: "NEW-HEAD-xyz"
    _, stats2 = verifier.run(store.load_memory())
    assert stats2["checked"] == 1  # перепроверка, не липкий VERIFIED


# =====================================================================
# LATENCY BUDGET (Q3: graceful degradation)
# =====================================================================


def test_budget_timeout_graceful_degradation(project: Path):
    store = IntelligenceStore(project)
    _seed(
        store,
        [
            _node("N1", "a", anchors=[{"kind": "import", "value": "fastmcp"}]),
            _node("N2", "b", anchors=[{"kind": "import", "value": "fastmcp"}]),
            _node("N3", "c", anchors=[{"kind": "import", "value": "fastmcp"}]),
        ],
    )
    verifier = _make_verifier(project, store)

    def slow_check(anchor, fp):
        import time as _t

        _t.sleep(0.02)  # 20ms на узел — бюджет 10ms будет превышен со 2-го узла
        return False

    verifier._check_anchor = slow_check
    memory, stats = verifier.run(store.load_memory(), budget_ms=10.0)
    assert stats["budget_exceeded"] is True
    # Обработан только первый узел; остальные остались в контексте без отзыва
    assert stats["checked"] == 1
    assert stats["refuted"] == 1
    remaining = [n["node_id"] for n in memory["adrs"]]
    assert set(remaining) == {"N2", "N3"}
    raw = {n["node_id"]: n for n in store._load_json("project_memory.json")}
    assert raw["N2"].get("status") != STATUS_REFUTED
    assert raw["N3"].get("status") != STATUS_REFUTED


# =====================================================================
# LAYER HOOK (Q3: default ON)
# =====================================================================


def test_layer_hook_verify_on_read_default_on(project: Path):
    layer = ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]
    layer.store.save_memory([_node("N1", "b", anchors=[{"kind": "import", "value": "grafana"}])])

    # По умолчанию verify_on_read=True -> узел отозван и скрыт
    mem = asyncio.run(layer.intel_get_project_memory())
    assert mem["adrs"] == []
    raw = layer.store._load_json("project_memory.json")[0]
    assert raw["status"] == STATUS_REFUTED
    assert raw["retract_source"] == RETRACT_SOURCE


def test_layer_hook_verify_on_read_off(project: Path):
    layer = ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]
    layer.store.save_memory([_node("N1", "b", anchors=[{"kind": "import", "value": "grafana"}])])

    mem = asyncio.run(layer.intel_get_project_memory(verify_on_read=False))
    assert [n["node_id"] for n in mem["adrs"]] == ["N1"]  # отключено: не проверялся
    assert layer.store._load_json("project_memory.json")[0].get("status", STATUS_ACTIVE) == STATUS_ACTIVE


def test_write_capture_makes_verify_effective_on_prose(project: Path):
    """Write-time capture (ADR-0003): prose-claim с 'import X' получает точный якорь
    при записи -> verify-on-read проверяет его (урок Exp 1-V: голые токены -> артефакты)."""
    layer = ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]
    asyncio.run(layer.intel_add_memory_node(
        "adrs", json.dumps({"claim": "транспорт использует import grafana"})
    ))
    asyncio.run(layer.intel_add_memory_node(
        "adrs", json.dumps({"claim": "транспорт использует import fastmcp"})
    ))

    mem = asyncio.run(layer.intel_get_project_memory())
    assert len(mem["adrs"]) == 1  # grafana-узел отозван, fastmcp-узел остался

    raw = {n["node_id"]: n for n in layer.store._load_json("project_memory.json")}
    grafana_node = next(n for n in raw.values() if "grafana" in n["data"]["claim"])
    assert grafana_node["status"] == STATUS_REFUTED
    assert grafana_node["retract_source"] == RETRACT_SOURCE
    assert "import:grafana" in grafana_node["retract_reason"]
    fastmcp_node = next(n for n in raw.values() if "fastmcp" in n["data"]["claim"])
    assert fastmcp_node["status"] == STATUS_VERIFIED
