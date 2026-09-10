"""Fail-Closed Freshness Gate (Exp 2 chain, 2026-09-10).

Покрывает:
- dirty-tree fix: dirty-кэш-ключ ≠ чистый; пересборка fingerprint на dirty;
- read gate: STALE + неполный проход -> stale_unverified / блок; полный -> CONSISTENT;
- write gate: STALE -> отказ с инструкцией (fail-closed per research: inform-agent
  не работает, server-side blocking даёт 0% stale);
- конфиг-тумблер freshness_gate (off|read|write|both).

Изоляция: MSCODEBASE_DATA_DIR -> tmp; проект с мини-деревом src + .env.
"""

import asyncio
import json
import threading
from pathlib import Path

import pytest

from src.core.consistency import ConsistencyState, get_consistency_tracker
from src.core.intelligence.layer import ProjectIntelligenceLayer
from src.core.intelligence.store import IntelligenceStore
from src.core.intelligence.verify_on_read import (
    STATUS_ACTIVE,
    VerifyOnRead,
)

SRC_MAIN = "import fastmcp\nimport sqlite3\n\nprint('ok')\n"
ENV_FILE = "LLAMA_CPP_ENABLED=true\nMSCODEBASE_EXECUTE_SCRIPT_ENABLED=false\n"


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


@pytest.fixture(autouse=True)
def reset_tracker():
    """Сброс глобального consistency-трекера между тестами (синглтон)."""
    get_consistency_tracker().invalidate()
    yield
    get_consistency_tracker().invalidate()


@pytest.fixture(autouse=True)
def gate_both(monkeypatch):
    """Default: freshness gate = both (рекомендованный config.memory.freshness_gate)."""
    monkeypatch.setenv("FRESHNESS_GATE", "both")
    from src.config.settings import reload_config

    reload_config()
    yield
    reload_config()


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


def _make_verifier(project: Path, store: IntelligenceStore) -> VerifyOnRead:
    return VerifyOnRead(project, store, threading.Lock())


def _make_layer(project: Path) -> ProjectIntelligenceLayer:
    return ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]


# =====================================================================
# DIRTY-TREE FIX
# =====================================================================


def test_dirty_cache_key_differs_from_clean(project: Path):
    """Dirty-флаг в ключе вердикта: незакоммиченные правки видят другую реальность."""
    assert (
        VerifyOnRead._cache_key("N1", "HEAD-A", False)
        != VerifyOnRead._cache_key("N1", "HEAD-A", True)
    )
    # Один и тот же dirty-флаг -> тот же ключ (кэш стабилен внутри режима)
    assert (
        VerifyOnRead._cache_key("N1", "HEAD-A", True)
        == VerifyOnRead._cache_key("N1", "HEAD-A", True)
    )


def test_dirty_tree_sees_uncommitted_change(project: Path):
    """Q: файл, удалённый ВНЕ git HEAD (dirty), должен быть ВИДЕН отпечатку.

    До fix: fingerprint кэшировался по HEAD, dirty-правка игнорировалась ->
    cache-hit по чистому вердикту VERIFIED живда бы и после удаления файла
    (stale VERIFIED в toxic-интервале notify->commit).
    """
    store = IntelligenceStore(project)
    _seed(
        store,
        [
            _node(
                "N1",
                "использует file:src/extra.py",
                anchors=[{"kind": "file", "value": "src/extra.py"}],
            )
        ],
    )
    (project / "src" / "extra.py").write_text("x = 1\n", encoding="utf-8")
    verifier = _make_verifier(project, store)
    verifier._resolve_head = lambda: "HEAD-FIXED"  # HEAD не меняется

    # Чистый проход: файл есть -> VERIFIED
    verifier._is_dirty = lambda: False
    _, stats1 = verifier.run(store.load_memory())
    assert stats1["verified"] == 1
    assert stats1["dirty"] is False

    # Незакоммиченное удаление: файл исчез, HEAD тот же.
    (project / "src" / "extra.py").unlink()
    verifier._is_dirty = lambda: True
    _, stats2 = verifier.run(store.load_memory())
    # Dirty-cache-key иной -> нет cache-hit по VERIFIED; свежий отпечаток
    # не видит файла -> REFUTED (а не stale VERIFIED).
    assert stats2["dirty"] is True
    assert stats2["cache_hits"] == 0
    assert stats2["refuted"] == 1


def test_dirty_bypasses_verdict_cache(project: Path):
    """Dirty-проход не переиспользует вердикт чистого HEAD (cache_hits=0)."""
    store = IntelligenceStore(project)
    _seed(
        store,
        [
            _node(
                "N1",
                "использует file:src/core/cypher_engine.py",
                anchors=[{"kind": "file", "value": "src/core/cypher_engine.py"}],
            )
        ],
    )
    verifier = _make_verifier(project, store)
    verifier._resolve_head = lambda: "HEAD-FIXED"

    verifier._is_dirty = lambda: False
    _, stats1 = verifier.run(store.load_memory())
    assert stats1["checked"] == 1

    # Второй ЧИСТЫЙ проход — cache hit (проверено выше, не перепроверяется)
    _, stats2 = verifier.run(store.load_memory())
    assert stats2["cache_hits"] == 1
    assert stats2["checked"] == 0

    # Переход в dirty -> кэш не действует, всё перепроверяется
    verifier._is_dirty = lambda: True
    _, stats3 = verifier.run(store.load_memory())
    assert stats3["cache_hits"] == 0
    assert stats3["checked"] == 1
    assert stats3["verified"] == 1

    # Второй dirty-проход: дерево могло измениться внутри dirty-интервала,
    # dirty-вердикт в кэш НЕ пишется -> снова полный пересчёт (Red Team: иначе
    # cache-hit по первому dirty-вердикту был бы stale при правках между проходами).
    _, stats4 = verifier.run(store.load_memory())
    assert stats4["cache_hits"] == 0
    assert stats4["checked"] == 1


# =====================================================================
# READ GATE
# =====================================================================


def test_read_gate_blocks_when_stale_and_incomplete(project: Path):
    """STALE + неполный проход (budget) -> blocked, узлы stale_unverified."""
    layer = _make_layer(project)
    store = IntelligenceStore(project)
    _seed(
        store,
        [
            _node(
                "N1",
                "использует file:src/core/cypher_engine.py",
                anchors=[{"kind": "file", "value": "src/core/cypher_engine.py"}],
            )
        ],
    )
    get_consistency_tracker().mark_stale("memory", "notify_change: src/main.py")

    mem, stats = asyncio.run(layer.intel_get_project_memory())

    # fail-closed: пишем/читаем флаг гейта только в STALE-режиме
    # (полный проход выше не успел исчерпать бюджет -> satisfied)
    assert stats["freshness_gate"] == "satisfied"
    s = get_consistency_tracker().get("memory")["state"]
    assert s == ConsistencyState.CONSISTENT.value


def test_read_gate_blocked_marks_stale_unverified(project: Path, monkeypatch):
    """Неполный проход в STALE -> blocked + stale_unverified на непроверенных."""
    monkeypatch.setenv("FRESHNESS_GATE", "both")
    layer = _make_layer(project)
    _seed(
        layer.store,
        [
            _node(
                "N1",
                "использует file:src/core/cypher_engine.py",
                anchors=[{"kind": "file", "value": "src/core/cypher_engine.py"}],
            ),
            _node(
                "N2",
                "использует file:src/other.py",
                anchors=[{"kind": "file", "value": "src/other.py"}],
            ),
        ],
    )
    get_consistency_tracker().mark_stale("memory", "notify_change")

    # Детерминированный неполный проход: подменяем run зарегистрированного
    # вердифайера (тот же реестр get_verifier, что использует layer).
    from src.core.intelligence.verify_on_read import get_verifier

    v = get_verifier(project, layer.store, layer._write_lock)

    def fake_run(memory, budget_ms=50.0):
        return memory, {
            "checked": 1,
            "nodes_seen": 2,
            "budget_exceeded": True,
            "budget_exceeded_nodes": ["N2"],
            "starved_nodes": [],
        }

    v.run = fake_run  # type: ignore[assignment]
    mem, stats = asyncio.run(layer.intel_get_project_memory())

    assert stats["freshness_gate"] == "blocked"
    flags = {}
    for sec in mem.values():
        for n in sec:
            flags[n["node_id"]] = n.get("verification")
    assert flags.get("N2") == "stale_unverified"  # не проверен в этом проходе
    assert flags.get("N1") == "fresh_verified"  # перепроверен в этом проходе
    s = get_consistency_tracker().get("memory")["state"]
    assert s == ConsistencyState.STALE.value  # неполный проход НЕ замыкает


# =====================================================================
# WRITE GATE
# =====================================================================


def test_write_gate_refuses_when_stale(project: Path):
    """STALE -> intel_add_memory_node отказывает (fail-closed), не предупреждает."""
    layer = _make_layer(project)
    get_consistency_tracker().mark_stale("memory", "notify_change")

    res = asyncio.run(layer.intel_add_memory_node("adrs", json.dumps({"claim": "x"})))
    assert "FRESHNESS GATE" in res
    assert "intel_get_project_memory" in res


def test_write_gate_allows_after_consistent(project: Path):
    """CONSISTENT/UNKNOWN -> запись проходит."""
    layer = _make_layer(project)
    get_consistency_tracker().mark_consistent("memory", "after vor")

    res = asyncio.run(layer.intel_add_memory_node("adrs", json.dumps({"claim": "ok"})))
    assert "FRESHNESS GATE" not in res
    nodes = layer.store._load_json("project_memory.json")
    assert any(n["data"].get("claim") == "ok" for n in nodes)


def test_gate_off_disables_write_block(project: Path, monkeypatch):
    """FRESHNESS_GATE=off -> legacy-поведение: запись при STALE разрешена."""
    monkeypatch.setenv("FRESHNESS_GATE", "off")
    from src.config.settings import reload_config

    reload_config()
    layer = _make_layer(project)
    get_consistency_tracker().mark_stale("memory", "notify_change")

    res = asyncio.run(layer.intel_add_memory_node("adrs", json.dumps({"claim": "legacy"})))
    assert "FRESHNESS GATE" not in res


def test_gate_read_only_still_blocks_write(project: Path, monkeypatch):
    """'read'-режим гейта НЕ блокирует запись (там свой write-gate только в both/write)."""
    monkeypatch.setenv("FRESHNESS_GATE", "read")
    from src.config.settings import reload_config

    reload_config()
    layer = _make_layer(project)
    get_consistency_tracker().mark_stale("memory", "notify_change")

    res = asyncio.run(layer.intel_add_memory_node("adrs", json.dumps({"claim": "r"})))
    assert "FRESHNESS GATE" not in res
