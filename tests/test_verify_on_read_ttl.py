"""H3 TTL-гниение (doc 10-continuous-verification, 2026-09-11).

Покрывает:
- last_checked пишется для КАЖДОГО проверенного узла (включая INCONCLUSIVE) —
  TTL-след существует, а не только для VERIFIED/REFUTED;
- rate-limit записи last_checked (LAST_CHECKED_MIN_INTERVAL): свежий след
  (< 6h) НЕ перетирается каждым тиком H1 idle;
- stale_ttl_nodes: узел жив (ACTIVE/VERIFIED), НЕ проверен в этом проходе
  (budget-голодание), след старше TTL_STALE_DAYS -> «не подтверждён за N дней»;
- нет следа вовсе (новый узел) -> НЕ stale (нет основания, starved ловит
  систематическое голодание отдельно);
- узел, проверенный в проходе (даже с древним следом) -> НЕ stale;
- cache-hit (второй проход на том же HEAD) тоже считается проверенным;
- слой (intel_get_project_memory) присваивает verification="stale_ttl".
"""

import asyncio
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core.intelligence.layer import ProjectIntelligenceLayer
from src.core.intelligence.store import IntelligenceStore
from src.core.intelligence.verify_on_read import (
    _TS_FMT,
    STATUS_ACTIVE,
    STATUS_VERIFIED,
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


def _make_verifier(project: Path, store: IntelligenceStore, lock=None) -> VerifyOnRead:
    return VerifyOnRead(project, store, lock or threading.Lock())


def _days_ago(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime(_TS_FMT)


# =====================================================================
# last_checked: пишется для проверенных (включая INCONCLUSIVE), rate-limit
# =====================================================================


def test_inconclusive_node_gets_last_checked(project: Path):
    """INCONCLUSIVE (без якорей) статус не меняется, но ТTL-след появляется."""
    store = IntelligenceStore(project)
    store.save_memory([_node("N3", "предпочтение владельца без следов в коде")])
    verifier = _make_verifier(project, store)

    memory, stats = verifier.run(store.load_memory())
    assert [n["node_id"] for n in memory["adrs"]] == ["N3"]
    assert stats["inconclusive"] == 1
    raw = store._load_json("project_memory.json")[0]
    assert raw.get("status", STATUS_ACTIVE) == STATUS_ACTIVE
    assert "verified_at" not in raw  # INCONCLUSIVE не VERIFIED
    assert "last_checked" in raw  # TTL-след «проверен <time>» есть
    try:
        datetime.strptime(raw["last_checked"], _TS_FMT)
    except ValueError:
        pytest.fail("last_checked не в expected-формате")


def test_last_checked_rate_limited_fresh_trace_kept(project: Path):
    """Свежий след (< LAST_CHECKED_MIN_INTERVAL) не перетирается каждым тиком —
    иначе H1 idle переписывал бы project_memory.json на каждый тик."""
    store = IntelligenceStore(project)
    node = _node("N3", "предпочтение владельца без следов в коде")
    node["last_checked"] = _days_ago(0)  # сейчас (младше 6h-порога)
    store.save_memory([node])
    verifier = _make_verifier(project, store)

    memory, _ = verifier.run(store.load_memory())
    assert [n["node_id"] for n in memory["adrs"]] == ["N3"]
    raw = store._load_json("project_memory.json")[0]
    assert raw["last_checked"] == node["last_checked"]  # не перезаписан


def test_last_checked_old_trace_refreshed(project: Path):
    """След старше порога обновляется — узел снова «проверен <now>»."""
    store = IntelligenceStore(project)
    node = _node("N3", "предпочтение владельца без следов в коде")
    node["last_checked"] = _days_ago(30)
    store.save_memory([node])
    verifier = _make_verifier(project, store)

    memory, _ = verifier.run(store.load_memory())
    assert [n["node_id"] for n in memory["adrs"]] == ["N3"]
    raw = store._load_json("project_memory.json")[0]
    assert raw["last_checked"] != node["last_checked"]  # обновлён на now


# =====================================================================
# stale_ttl: не проверен в проходе + древний след
# =====================================================================


def _run_with_budget_second_node_starved(store, project, first_node, second_node):
    """budget_ms=0: первый узел проверяется (nodes_seen>1 условие ложно),
    второй — budget_exceeded (не touched). Возвращает (stats, raw_by_id)."""
    store.save_memory([first_node, second_node])
    verifier = _make_verifier(project, store)
    memory, stats = verifier.run(store.load_memory(), budget_ms=0.0)
    raw = {n["node_id"]: n for n in store._load_json("project_memory.json")}
    return stats, raw


def test_stale_ttl_unvisited_ancient_trace_flagged(project: Path):
    """VERIFIED-узел со следом старше TTL, не проверенный в проходе (бюджет),
    -> stale_ttl_nodes. Потребитель видит, что узел «не подтверждён за N дней»."""
    store = IntelligenceStore(project)
    n1 = _node("N1", "использует sqlite3", anchors=[{"kind": "import", "value": "sqlite3"}])
    n2 = _node("N2", "использует sqlite3", anchors=[{"kind": "import", "value": "sqlite3"}])
    n2["status"] = STATUS_VERIFIED
    n2["verified_at"] = _days_ago(40)  # древний след (> TTL_STALE_DAYS=30)

    stats, raw = _run_with_budget_second_node_starved(store, project, n1, n2)
    assert stats["budget_exceeded"] is True
    assert stats["stale_ttl_nodes"] == ["N2"]
    assert raw["N2"].get("status") == STATUS_VERIFIED  # статус НЕ меняется
    assert "retracted_at" not in raw["N2"]  # не REFUTED (Red Team a2)


def test_stale_ttl_fresh_trace_not_flagged(project: Path):
    """VERIFIED-узел с недавним следом, не проверенный в проходе, -> НЕ stale."""
    store = IntelligenceStore(project)
    n1 = _node("N1", "использует sqlite3", anchors=[{"kind": "import", "value": "sqlite3"}])
    n2 = _node("N2", "использует sqlite3", anchors=[{"kind": "import", "value": "sqlite3"}])
    n2["status"] = STATUS_VERIFIED
    n2["verified_at"] = _days_ago(2)  # свежий след

    stats, _ = _run_with_budget_second_node_starved(store, project, n1, n2)
    assert stats.get("stale_ttl_nodes", []) == []


def test_stale_ttl_no_trace_not_flagged(project: Path):
    """Нет следа вовсе (новый узел) -> НЕ stale: нет основания флагать,
    систематическое голодание ловит starved отдельно."""
    store = IntelligenceStore(project)
    n1 = _node("N1", "использует sqlite3", anchors=[{"kind": "import", "value": "sqlite3"}])
    n2 = _node("N2", "использует sqlite3", anchors=[{"kind": "import", "value": "sqlite3"}])
    # n1 без статуса (легаси -> ACTIVE), n2 тоже без verified_at/last_checked

    stats, _ = _run_with_budget_second_node_starved(store, project, n1, n2)
    assert stats.get("stale_ttl_nodes", []) == []


def test_stale_ttl_checked_node_not_flagged(project: Path):
    """Узел с древним следом, но ПРОВЕРЕННЫЙ в проходе -> НЕ stale:
    перепроверка жива, «гниения» нет."""
    store = IntelligenceStore(project)
    n1 = _node("N1", "использует sqlite3", anchors=[{"kind": "import", "value": "sqlite3"}])
    n1["status"] = STATUS_VERIFIED
    n1["verified_at"] = _days_ago(40)  # древний след, но он будет перепроверен
    store.save_memory([n1])
    verifier = _make_verifier(project, store)
    memory, stats = verifier.run(store.load_memory())  # бюджет по умолчанию хватает

    assert [n["node_id"] for n in memory["adrs"]] == ["N1"]
    assert stats.get("stale_ttl_nodes", []) == []  # touched -> не stale


def test_stale_ttl_cache_hit_not_flagged_second_pass(project: Path):
    """Второй проход на том же HEAD — cache-hit — тоже считается проверенным
    (touched): stale не флагается даже при древнем verified_at."""
    store = IntelligenceStore(project)
    n1 = _node("N1", "использует sqlite3", anchors=[{"kind": "import", "value": "sqlite3"}])
    n1["status"] = STATUS_VERIFIED
    n1["verified_at"] = _days_ago(40)
    store.save_memory([n1])
    verifier = _make_verifier(project, store)

    memory, stats1 = verifier.run(store.load_memory())
    assert stats1.get("stale_ttl_nodes", []) == []
    assert stats1["checked"] == 1  # первый проход — свежая проверка

    memory2, stats2 = verifier.run(store.load_memory())
    assert stats2["cache_hits"] == 1  # второй — cache-hit (тоже touched)
    assert stats2.get("stale_ttl_nodes", []) == []
    assert [n["node_id"] for n in memory2["adrs"]] == ["N1"]


# =====================================================================
# слой: флаг verification="stale_ttl" в intel_get_project_memory
# =====================================================================


def test_layer_marks_stale_ttl_flag(project: Path, monkeypatch):
    """Слой присваивает verification="stale_ttl" узлам из stats — потребитель
    памяти видит label «не подтверждён за N дней» (как stale_unverified)."""
    import src.core.intelligence.verify_on_read as vor_mod

    node = _node("N1", "использует sqlite3", anchors=[{"kind": "import", "value": "sqlite3"}])
    node["status"] = STATUS_VERIFIED
    store = IntelligenceStore(project)
    store.save_memory([node])

    class _FakeVerifier:
        def run(self, memory):
            return memory, {"stale_ttl_nodes": ["N1"]}

    monkeypatch.setattr(vor_mod, "get_verifier", lambda *a, **k: _FakeVerifier())

    layer = ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]
    mem, _stats = asyncio.run(layer.intel_get_project_memory())
    assert mem["adrs"][0]["verification"] == "stale_ttl"
    assert mem["adrs"][0]["status"] == STATUS_VERIFIED
