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
    STATUS_SUPERSEDED,
    STATUS_VERIFIED,
    VerifyOnRead,
    _Fingerprint,
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


def test_extract_anchors_write_path_filters_missing_files(project):
    """P2: write-path отбрасывает file-якоря, которых нет относительно корня
    (слепленные/относительные пути из вольного текста коммитов)."""
    node = _node(
        "N1",
        "version sync: src/main.py и src/core/cypher_engine.py, "
        "плюс pyproject/extension.toml/__init__.py для синка",
    )
    anchors = extract_anchors(node, project_root=project)
    kinds = {(a.kind, a.value) for a in anchors}
    assert ("file", "src/main.py") in kinds
    assert ("file", "src/core/cypher_engine.py") in kinds
    assert ("file", "pyproject/extension.toml/__init__.py") not in kinds


def test_extract_anchors_write_path_strips_punctuation(project):
    """P2: завершающая пунктуация обрезается — «src/.../cypher_engine.py.» валиден."""
    node = _node("N1", "используется file:src/core/cypher_engine.py.")
    anchors = extract_anchors(node, project_root=project)
    assert ("file", "src/core/cypher_engine.py") in {(a.kind, a.value) for a in anchors}


def test_extract_anchors_explicit_anchors_filtered(project):
    """P2: явные data.anchors с несуществующим файлом тоже отбрасываются на write-path."""
    node = _node(
        "N1", "claim",
        anchors=[
            {"kind": "file", "value": "src/core/cypher_engine.py"},
            {"kind": "file", "value": "queries/__init__.py"},
            {"kind": "file", "value": "src/core/cypher_engine.py."},
        ],
    )
    anchors = extract_anchors(node, project_root=project)
    kinds = {(a.kind, a.value) for a in anchors}
    assert ("file", "src/core/cypher_engine.py") in kinds
    assert ("file", "queries/__init__.py") not in kinds
    assert ("file", "src/core/cypher_engine.py.") not in kinds


def test_extract_anchors_read_path_backward_compat():
    """P2: без project_root (read-path) поведение не меняется: мусорные пути
    остаются якорями — классификация честная (дрейф -> REFUTED)."""
    node = _node("N1", "упоминание pyproject/extension.toml/__init__.py")
    anchors = extract_anchors(node)
    assert ("file", "pyproject/extension.toml/__init__.py") in {
        (a.kind, a.value) for a in anchors
    }


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


def test_terminal_superseded_not_rewritten_to_verified(project: Path):
    """Терминальный SUPERSEDED не откатывается в VERIFIED verify-on-read'ом.

    Защита в _persist_transitions: узлы с живыми якорями и терминальным
    статусом остаются в истории как есть (прямой прогон — как при аудите
    include_retracted, в обход фильтра store.load_memory).
    """
    store = IntelligenceStore(project)
    node = _node("N1", "a", anchors=[{"kind": "import", "value": "fastmcp"}], status=STATUS_SUPERSEDED)
    _seed(store, [node])
    verifier = _make_verifier(project, store)

    memory, stats = verifier.run({"adrs": [node]})
    raw = store._load_json("project_memory.json")[0]
    assert raw["status"] == STATUS_SUPERSEDED
    assert "verified_at" not in raw
    assert stats["verified"] == 1  # вердикт посчитан, но переход не применён
    assert memory["adrs"][0]["node_id"] == "N1"


def test_terminal_refuted_not_rewritten_to_verified(project: Path):
    """REFUTED с живыми якорями не возвращается в VERIFIED (аудит-путь)."""
    store = IntelligenceStore(project)
    node = _node("N1", "a", anchors=[{"kind": "import", "value": "fastmcp"}], status=STATUS_REFUTED)
    _seed(store, [node])
    verifier = _make_verifier(project, store)

    verifier.run({"adrs": [node]})
    raw = store._load_json("project_memory.json")[0]
    assert raw["status"] == STATUS_REFUTED
    assert "verified_at" not in raw


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


def test_budget_exceeded_nodes_recorded_in_stats(project: Path):
    """Пол Тома: непроверенные из-за бюджета узлы попадают в stats.budget_exceeded_nodes,
    чтобы потребитель видел checked/total, а не принимал вчерашний статус за свежий."""
    store = IntelligenceStore(project)
    _seed(
        store,
        [
            _node(f"N{i}", "c", anchors=[{"kind": "import", "value": "fastmcp"}])
            for i in range(1, 6)
        ],
    )
    verifier = _make_verifier(project, store)

    def slow_check(anchor, fp):
        import time as _t

        _t.sleep(0.02)  # 20ms/узел — бюджет 10ms исчерпан со 2-го узла
        return True

    verifier._check_anchor = slow_check
    memory, stats = verifier.run(store.load_memory(), budget_ms=10.0)
    assert stats["budget_exceeded"] is True
    assert stats["checked"] == 1  # обработан только первый узел
    assert set(stats["budget_exceeded_nodes"]) == {"N2", "N3", "N4", "N5"}
    # Непроверенные узлы остались в контексте и не отозваны
    assert {n["node_id"] for n in memory["adrs"]} == {"N1", "N2", "N3", "N4", "N5"}


def test_layer_budget_exceeded_flags_nodes(project: Path, monkeypatch):
    """Слой помечает непроверенные узлы verification="budget_exceeded" — их статус
    унаследован от прошлых циклов, а не подтверждён в этом чтении (пол Тома)."""
    layer = ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]
    nodes = [
        _node(f"N{i}", "c", anchors=[{"kind": "import", "value": "fastmcp"}])
        for i in range(5)
    ]
    layer.store.save_memory(nodes)

    def slow_check(self, anchor, fp):
        import time as _t

        _t.sleep(0.03)
        return True

    monkeypatch.setattr(VerifyOnRead, "_check_anchor", slow_check)
    mem, stats = asyncio.run(layer.intel_get_project_memory())
    assert stats["budget_exceeded"] is True
    assert stats["checked"] < stats["nodes_seen"]  # часть узлов не проверена
    # Флаг стоит ровно на узлах, которые run() пометил как непроверенные
    flagged = {
        n["node_id"]
        for sec in mem.values()
        for n in sec
        if n.get("verification") == "budget_exceeded"
    }
    assert flagged == set(stats["budget_exceeded_nodes"])
    assert flagged  # хотя бы один помечен
    # Обработанные узлы флага не несут
    processed = {
        n["node_id"]
        for sec in mem.values()
        for n in sec
        if n.get("verification") is None
    }
    assert len(processed) == stats["checked"]


# =====================================================================
# LAYER HOOK (Q3: default ON)
# =====================================================================


def test_layer_hook_verify_on_read_default_on(project: Path):
    layer = ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]
    layer.store.save_memory([_node("N1", "b", anchors=[{"kind": "import", "value": "grafana"}])])

    # По умолчанию verify_on_read=True -> узел отозван и скрыт
    mem, stats = asyncio.run(layer.intel_get_project_memory())
    assert mem["adrs"] == []
    assert stats["nodes_seen"] == 1 and stats["checked"] == 1 and stats["refuted"] == 1
    assert stats["metrics"]["total"] == 1  # снятие метрик в ресипте
    raw = layer.store._load_json("project_memory.json")[0]
    assert raw["status"] == STATUS_REFUTED
    assert raw["retract_source"] == RETRACT_SOURCE


def test_layer_hook_verify_on_read_off(project: Path):
    layer = ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]
    layer.store.save_memory([_node("N1", "b", anchors=[{"kind": "import", "value": "grafana"}])])

    mem, stats = asyncio.run(layer.intel_get_project_memory(verify_on_read=False))
    assert [n["node_id"] for n in mem["adrs"]] == ["N1"]  # отключено: не проверялся
    assert stats["verify_on_read"] is False  # ресипт: VOR выключен
    assert "metrics" in stats  # метрики приходят и без VOR
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

    mem, _stats = asyncio.run(layer.intel_get_project_memory())
    assert len(mem["adrs"]) == 1  # grafana-узел отозван, fastmcp-узел остался

    raw = {n["node_id"]: n for n in layer.store._load_json("project_memory.json")}
    grafana_node = next(n for n in raw.values() if "grafana" in n["data"]["claim"])
    assert grafana_node["status"] == STATUS_REFUTED
    assert grafana_node["retract_source"] == RETRACT_SOURCE
    assert "import:grafana" in grafana_node["retract_reason"]
    fastmcp_node = next(n for n in raw.values() if "fastmcp" in n["data"]["claim"])
    assert fastmcp_node["status"] == STATUS_VERIFIED


# =====================================================================
# MATCHED/DELIVERED (Том, 2026-08-16)
# =====================================================================


def test_counters_matched_delivered_fresh_and_cache_hit(project: Path):
    """Том: свежая проверка и cache-hit — обе считаются доставкой (delivered)."""
    store = IntelligenceStore(project)
    _seed(store, [_node("N1", "a", anchors=[{"kind": "import", "value": "fastmcp"}])])
    verifier = _make_verifier(project, store)

    _, stats1 = verifier.run(store.load_memory())
    assert stats1["checked"] == 1
    assert verifier._cache["counters"]["N1"] == {"matched": 1, "delivered": 1}
    assert "starved_nodes" not in stats1

    # Тот же HEAD -> cache-hit, но вердикт разрешён -> доставка
    _, stats2 = verifier.run(store.load_memory())
    assert stats2["cache_hits"] == 1
    assert verifier._cache["counters"]["N1"] == {"matched": 2, "delivered": 2}
    assert "starved_nodes" not in stats2


def test_starved_node_seen_never_delivered(project: Path):
    """Том: MATCHED>0, DELIVERED=0 два цикла подряд -> starved (голодание по бюджету)."""
    store = IntelligenceStore(project)
    _seed(
        store,
        [
            _node("N1", "a", anchors=[{"kind": "import", "value": "fastmcp"}]),
            _node("N2", "b", anchors=[{"kind": "import", "value": "fastmcp"}]),
        ],
    )
    verifier = _make_verifier(project, store)

    def slow_check(anchor, fp):
        import time as _t

        _t.sleep(0.02)  # 20ms на узел: бюджет 10ms режется со 2-го узла
        return True

    verifier._check_anchor = slow_check
    _, stats1 = verifier.run(store.load_memory(), budget_ms=10.0)
    # N1 (первый узел вне бюджета) проверен; N2 виден, но не проверен
    assert stats1["checked"] == 1
    assert verifier._cache["counters"]["N2"] == {"matched": 1, "delivered": 0}
    assert "starved_nodes" not in stats1  # одного цикла мало

    # Смена HEAD -> N1 снова проверяется (медленно) и снова вытесняет N2 из бюджета.
    # Без смены HEAD N1 был бы cache-hit (~0ms), бюджет не исчерпался бы и N2
    # проверился бы — голодание требует реальной работы на каждом цикле.
    verifier._resolve_head = lambda: "HEAD-B"
    _, stats2 = verifier.run(store.load_memory(), budget_ms=10.0)
    assert verifier._cache["counters"]["N2"] == {"matched": 2, "delivered": 0}
    # N2 видим 2 цикла, но ни разу не доставлен -> starved; N1 не голодает
    assert stats2["starved_nodes"] == ["N2"]


def test_counters_survive_head_change(project: Path):
    """Счётчики ключуются node_id (не head) — переживают смену HEAD, в отличие от verdicts."""
    store = IntelligenceStore(project)
    _seed(store, [_node("N1", "a", anchors=[{"kind": "import", "value": "fastmcp"}])])
    verifier = _make_verifier(project, store)

    verifier.run(store.load_memory())
    verifier._resolve_head = lambda: "NEW-HEAD-abc123"
    _, stats2 = verifier.run(store.load_memory())
    assert stats2["checked"] == 1  # смена HEAD -> перепроверка
    assert verifier._cache["counters"]["N1"] == {"matched": 2, "delivered": 2}


def test_counters_persist_to_cache_file(project: Path):
    """Счётчики персистятся в verify_cache.json — переживают перезапуск процесса."""
    store = IntelligenceStore(project)
    _seed(store, [_node("N1", "a", anchors=[{"kind": "import", "value": "fastmcp"}])])
    verifier = _make_verifier(project, store)

    verifier.run(store.load_memory())
    data = json.loads(verifier.cache_file.read_text(encoding="utf-8"))
    assert data["counters"]["N1"] == {"matched": 1, "delivered": 1}

    # Новый экземпляр читает сохранённые счётчики (кэш-файл = история)
    verifier2 = _make_verifier(project, store)
    assert verifier2._cache["counters"]["N1"] == {"matched": 1, "delivered": 1}


def test_layer_starved_flags_nodes(project: Path, monkeypatch):
    """Слой помечает starved-узлы verification="starved" (кумулятивный сигнал
    голодания), а разовые budget_exceeded — своим флагом; starved не перетирается."""
    layer = ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]
    nodes = [
        _node(f"N{i}", "c", anchors=[{"kind": "import", "value": "fastmcp"}])
        for i in range(5)
    ]
    layer.store.save_memory(nodes)

    def slow_check(self, anchor, fp):
        import time as _t

        _t.sleep(0.03)
        return True

    monkeypatch.setattr(VerifyOnRead, "_check_anchor", slow_check)
    asyncio.run(layer.intel_get_project_memory())  # цикл 1: хвост виден, не доставлен
    mem, stats = asyncio.run(layer.intel_get_project_memory())  # цикл 2: хвост starved
    assert stats["starved_nodes"]  # как минимум один систематически голодает
    flagged_starved = {
        n["node_id"] for sec in mem.values() for n in sec if n.get("verification") == "starved"
    }
    assert flagged_starved == set(stats["starved_nodes"])
    flagged_budget = {
        n["node_id"]
        for sec in mem.values()
        for n in sec
        if n.get("verification") == "budget_exceeded"
    }
    assert flagged_budget == set(stats["budget_exceeded_nodes"]) - set(stats["starved_nodes"])


# =====================================================================
# ADR-0005: pkg:-якоря (closed-world манифест) — dist name vs import path
# =====================================================================


PYPROJECT_MANIFEST = (
    "[project]\n"
    "name = \"probe\"\n"
    "version = \"0.1.0\"\n"
    "dependencies = [\n"
    '    "fastmcp>=1.0.0",\n'
    '    "PyYAML>=6.0",\n'
    "]\n"
)


def _write_manifest(project: Path, text: str = PYPROJECT_MANIFEST) -> None:
    (project / "pyproject.toml").write_text(text, encoding="utf-8")


def test_extract_anchors_explicit_pkg_syntax(project: Path):
    """ADR-0005: явный синтаксис `pkg:name` даёт pkg:-якорь на обоих путях."""
    anchors = extract_anchors({"data": {"claim": "фоновые задачи — pkg:celery"}})
    pkgs = [(a.kind, a.value) for a in anchors if a.kind == "pkg"]
    assert pkgs == [("pkg", "celery")]


def test_extract_anchors_write_path_captures_prose_manifest_pkg(project: Path):
    """ADR-0005: write-path — слово прозы, совпадающее с зависимостью манифеста,
    становится pkg:-якорем (fastmcp-класс: dist name известен манифесту)."""
    _write_manifest(project)
    anchors = extract_anchors(
        {"data": {"claim": "транспорт использует fastmcp"}}, project_root=project
    )
    pkgs = [(a.kind, a.value) for a in anchors if a.kind == "pkg"]
    assert pkgs == [("pkg", "fastmcp")]


def test_write_path_no_pkg_anchor_for_word_not_in_manifest(project: Path):
    """ADR-0005: stdlib вне скоупа — sqlite3 нет в манифесте -> НЕ pkg:-якорь
    (нет ложного REFUTED/VERIFIED; Skillselion: stdlib falls out of scope)."""
    _write_manifest(project)
    anchors = extract_anchors(
        {"data": {"claim": "локальный кэш использует sqlite3"}}, project_root=project
    )
    assert all(a.kind != "pkg" for a in anchors)


def test_pkg_anchor_found_verified_included(project: Path):
    """ADR-0005: pkg:-якорь, найденный в манифесте -> VERIFIED, узел виден."""
    _write_manifest(project)
    store = IntelligenceStore(project)
    _seed(store, [_node("N1", "a", anchors=[{"kind": "pkg", "value": "fastmcp"}])])
    verifier = _make_verifier(project, store)
    memory, stats = verifier.run(store.load_memory())
    assert stats["verified"] == 1
    assert [n["node_id"] for n in memory["adrs"]] == ["N1"]
    assert store._load_json("project_memory.json")[0]["status"] == STATUS_VERIFIED


def test_pkg_anchor_absent_refuted_excluded(project: Path):
    """ADR-0005: closed-world — явный pkg:-якорь, отсутствующий в манифесте,
    -> REFUTED (SILENT_ABSENCE), узел исключён из контекста."""
    _write_manifest(project)
    store = IntelligenceStore(project)
    _seed(store, [_node("N1", "a", anchors=[{"kind": "pkg", "value": "celery"}])])
    verifier = _make_verifier(project, store)
    memory, stats = verifier.run(store.load_memory())
    assert stats["refuted"] == 1
    assert memory["adrs"] == []
    raw = store._load_json("project_memory.json")[0]
    assert raw["status"] == STATUS_REFUTED
    assert REASON_SILENT_ABSENCE in raw["retract_reason"]
    assert "pkg:celery" in raw["retract_reason"]
    assert raw["retract_source"] == RETRACT_SOURCE


def test_dist_name_pyyaml_prose_verified_via_manifest(project: Path):
    """ADR-0005: dist name ≠ import path — проза «PyYAML» сверяется с манифестом
    (нормализация PEP 503: pyyaml), а не с src-импортами (yaml). Закрывает класс
    ложных REFUTED из Exp 1-V (fastmcp: from mcp.server.fastmcp import ...)."""
    _write_manifest(project)
    # claim «используем PyYAML»: write-path даёт pkg:PyYAML, src-импорта yaml нет
    layer = ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]
    asyncio.run(layer.intel_add_memory_node(
        "adrs", json.dumps({"claim": "конфиги парсим через PyYAML"})
    ))
    mem, _stats = asyncio.run(layer.intel_get_project_memory())
    assert len(mem["adrs"]) == 1  # не отозван, несмотря на отсутствие import yaml в src
    raw = layer.store._load_json("project_memory.json")[0]
    assert raw["status"] == STATUS_VERIFIED
    pkg_anchors = [a for a in raw["data"].get("anchors", []) if a["kind"] == "pkg"]
    assert pkg_anchors and pkg_anchors[0]["value"] == "PyYAML"


def test_cache_schema_guard_rebuilds_without_packages(project: Path, tmp_path: Path):
    """ADR-0005 schema guard: кэш старого формата (fingerprint без 'packages')
    пересобирается — иначе пустой набор ложно REFUTED'ил бы pkg:-якоря."""
    _write_manifest(project)
    store = IntelligenceStore(project)
    _seed(store, [_node("N1", "a", anchors=[{"kind": "pkg", "value": "fastmcp"}])])
    cache_file = tmp_path / "verify_cache.json"
    cache_file.write_text(
        json.dumps({
            "head": "stale",
            "fingerprint": {"imports": [], "files": [], "env_keys": []},  # без packages
            "verdicts": {},
        }),
        encoding="utf-8",
    )
    verifier = VerifyOnRead(project, store, threading.Lock(), cache_file=cache_file)
    memory, stats = verifier.run(store.load_memory())
    assert stats["checked"] == 1
    assert [n["node_id"] for n in memory["adrs"]] == ["N1"]  # VERIFIED, не REFUTED


# =====================================================================
# ADR-0005 guard (C-гибрид): проза-«import X» с частотным словом без src-импорта
# =====================================================================


def test_prose_import_common_word_not_in_src_dropped_write_path(project: Path):
    """Guard: «dist name ≠ import path» (частотное слово, нет в src) НЕ даёт
    import:-якорь на write-path (инцидент NODE-cc88d2)."""
    anchors = extract_anchors(
        {"data": {"claim": "dist name ≠ import path для анкоров"}}, project_root=project
    )
    assert all(a.kind != "import" for a in anchors)


def test_prose_import_common_word_not_in_src_dropped_read_path(project: Path):
    """Guard на read-path: run()-путь (src_imports=fp.imports) тоже отсевает
    проза-«import path» — иначе ложный отзыв вернулся бы при извлечении."""
    fp = _Fingerprint(root=project)
    anchors = extract_anchors(
        {"data": {"claim": "dist name ≠ import path"}}, src_imports=fp.imports
    )
    assert all(a.kind != "import" for a in anchors)


def test_prose_import_path_node_not_refuted(project: Path):
    """Конец-в-конец: узел с прозой «import path» НЕ отзывается (инцидент)."""
    store = IntelligenceStore(project)
    _seed(store, [_node("N1", "dist name ≠ import path", status=STATUS_ACTIVE)])
    verifier = _make_verifier(project, store)
    memory, stats = verifier.run(store.load_memory())
    assert stats["refuted"] == 0
    assert [n["node_id"] for n in memory["adrs"]] == ["N1"]
    assert store._load_json("project_memory.json")[0].get("status", STATUS_ACTIVE) == STATUS_ACTIVE


def test_prose_import_common_word_in_src_kept(project: Path):
    """Guard: «import time» при time реально импортированном в src — якорь
    сохраняется (реальный импорт не теряем)."""
    (project / "src" / "utils.py").write_text("import time\n", encoding="utf-8")
    anchors = extract_anchors(
        {"data": {"claim": "замеры через import time"}}, project_root=project
    )
    assert [a.value for a in anchors if a.kind == "import"] == ["time"]


def test_prose_import_rare_word_not_in_src_kept(project: Path):
    """Guard: grafana (редкое слово, нет в src) сохраняется — SILENT-детекция
    и smoke-негативный контроль остаются рабочими."""
    anchors = extract_anchors(
        {"data": {"claim": "транспорт использует import grafana"}}, project_root=project
    )
    assert [a.value for a in anchors if a.kind == "import"] == ["grafana"]


def test_explicit_import_anchors_not_guarded(project: Path):
    """Guard фильтрует только прозу: явные data.anchors import:path (намеренный
    якорь автора) не отбрасываются."""
    anchors = extract_anchors(
        {
            "data": {
                "claim": "x",
                "anchors": [{"kind": "import", "value": "path"}],
            }
        },
        project_root=project,
    )
    assert any(a.kind == "import" and a.value == "path" for a in anchors)
