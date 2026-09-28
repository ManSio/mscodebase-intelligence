#!/usr/bin/env python3
"""Holdout-harness single-loop guard (2026-09-28).

Regression: the per-query `asyncio.run()` pattern silently degrades every
even-positioned query to reranker passthrough (provider-None, reranker_ms=0),
because asyncio primitives bound to the first, now-closed loop misbehave on
alternating fresh loops. Both gate scripts must run ALL queries inside ONE
event loop (`asyncio.run(_run_all(...))` exactly once) and fail loudly on
degraded rows (reranker_ms falsy) instead of judging rank on passthrough.

Unit-level (no live services): AST structural guard + fake-searcher
loop-identity probe. Live probe is best-effort, skipped if services down.
"""
import ast
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GATES = ["scripts/o1_holdout_gate.py", "scripts/p2_holdout_gate.py"]


def _run_calls(tree: ast.AST) -> int:
    """Count real asyncio.run() CALLS (docstring mentions don't parse as calls)."""
    n = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "asyncio"
        ):
            n += 1
    return n


def _has_coro(tree: ast.AST, name: str) -> bool:
    return any(
        isinstance(node, ast.AsyncFunctionDef) and node.name == name
        for node in ast.walk(tree)
    )


@pytest.mark.parametrize("gate", GATES)
def test_single_event_loop_per_gate(gate):
    """Reintroducing per-query asyncio.run() (count != 1) fails here."""
    src = (ROOT / gate).read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert _run_calls(tree) == 1, f"{gate}: expected exactly 1 asyncio.run() call"
    assert _has_coro(tree, "_run_all"), f"{gate}: missing `async def _run_all`"


@pytest.mark.parametrize("gate", GATES)
def test_degraded_flag_present(gate):
    """Both gates must fail loudly on reranker passthrough (reranker_ms falsy)."""
    src = (ROOT / gate).read_text(encoding="utf-8")
    assert "degraded" in src, f"{gate}: missing degraded-flag handling"


class _FakeCache:
    def clear(self):
        pass


class _FakeSearcher:
    """Records the running loop of every query; always reports real timing."""

    def __init__(self):
        self.loops = []
        self._reranker_cache = _FakeCache()
        self._multi_reranker = None
        self._last_rerank_timing = {"reranker_ms": 12.5, "model": "fake"}

    def _build_fts5_index(self):
        pass

    async def hybrid_search_async(self, query, limit=5):
        self.loops.append(id(asyncio.get_running_loop()))
        return [{"metadata": {"file": "x.py"}, "identifier_boost": False}]


async def _drive(module_name, cases_attr_unused=None):
    import importlib

    mod = importlib.import_module(module_name)
    searcher = _FakeSearcher()
    rows = await mod._run_all(searcher)
    return searcher, rows


async def test_o1_all_queries_share_one_loop():
    """All queries in o1 _run_all execute on the SAME event loop."""
    searcher, rows = await _drive("scripts.o1_holdout_gate")
    assert len(rows) > 1
    assert len(set(searcher.loops)) == 1, "queries ran on different event loops"
    # +1: the discarded warm-up query also runs on the same loop.
    assert len(searcher.loops) == len(rows) + 1
    assert all(not r["degraded"] for r in rows), "fake timing must not flag degraded"


async def test_p2_all_queries_share_one_loop():
    """All queries in p2 _run_all execute on the SAME event loop."""
    searcher, rows = await _drive("scripts.p2_holdout_gate")
    assert len(rows) > 1
    assert len(set(searcher.loops)) == 1, "queries ran on different event loops"
    # +1: the discarded warm-up query also runs on the same loop.
    assert len(searcher.loops) == len(rows) + 1
    assert all(not r["degraded"] for r in rows), "fake timing must not flag degraded"


async def test_live_probe_no_passthrough_cluster():
    """Tiny live probe: 2 queries on ONE loop, no zero-ms passthrough cluster.

    Skipped when live services are unavailable (unit-level guards above still run).
    """
    try:
        from scripts.o1_holdout_gate import build_searcher
    except Exception as e:  # noqa: BLE001 — import env issue -> skip live only
        pytest.skip(f"live probe unavailable (import): {e}")
    try:
        searcher = build_searcher(ROOT)
        timings = []
        for q in ("warmup cold start primer", "hybrid_search_async BM25 vector"):
            await searcher.hybrid_search_async(q, limit=3)
            timings.append(dict(getattr(searcher, "_last_rerank_timing", None) or {}))
    except Exception as e:  # noqa: BLE001 — services down -> skip live only
        pytest.skip(f"live probe unavailable (services): {e}")
    if searcher._multi_reranker is None:
        pytest.skip("live probe unavailable: no reranker service (unit-level only)")
    zeros = sum(1 for t in timings if not t.get("reranker_ms"))
    assert zeros == 0, f"live passthrough cluster: {timings}"
