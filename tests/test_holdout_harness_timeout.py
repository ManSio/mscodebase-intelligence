#!/usr/bin/env python3
"""Holdout-harness per-query timeout guard (2026-09-28).

Regression: one hung `hybrid_search_async` must fail its row (timed_out,
evaluated like void/degraded in main()) — never hang the whole gate.
Style follows tests/test_holdout_harness_loop.py: fake searchers, no live
services. Timeout is overridden via monkeypatch — never waits 120s in test.
"""

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GATES = ["scripts.o1_holdout_gate", "scripts.p2_holdout_gate"]

WARMUP = "warmup cold start primer"


class _FakeCache:
    def clear(self):
        pass


class _BaseFake:
    def __init__(self):
        self._reranker_cache = _FakeCache()
        self._multi_reranker = None
        self._last_rerank_timing = {"reranker_ms": 12.5, "model": "fake"}

    def _build_fts5_index(self):
        pass

    def _row(self, query):
        return [{"metadata": {"file": "x.py"}, "identifier_boost": False}]


class _HangingSearcher(_BaseFake):
    """Hangs on every measured query; warm-up stays fast (one-hung-query model)."""

    async def hybrid_search_async(self, query, limit=5):
        if query == WARMUP:
            return self._row(query)
        await asyncio.sleep(60)
        return self._row(query)  # pragma: no cover — cancelled by wait_for


class _FastSearcher(_BaseFake):
    async def hybrid_search_async(self, query, limit=5):
        return self._row(query)


@pytest.mark.parametrize("module_name", GATES)
def test_hung_query_becomes_timed_out_fail_row(module_name, monkeypatch):
    """A hung query yields timed_out rows quickly (short timeout override)."""
    mod = importlib.import_module(module_name)
    monkeypatch.setattr(mod, "QUERY_TIMEOUT", 0.05)
    rows = asyncio.run(mod._run_all(_HangingSearcher()))
    assert len(rows) > 1
    assert all(r["timed_out"] for r in rows), "hung queries must flag timed_out"


@pytest.mark.parametrize("module_name", GATES)
def test_fast_searcher_no_timeout_positive_control(module_name, monkeypatch):
    """Positive control: a fast searcher never flags timed_out."""
    mod = importlib.import_module(module_name)
    monkeypatch.setattr(mod, "QUERY_TIMEOUT", 5)
    rows = asyncio.run(mod._run_all(_FastSearcher()))
    assert len(rows) > 1
    assert all(not r["timed_out"] for r in rows)


@pytest.mark.parametrize("module_name", GATES)
def test_main_fails_gate_on_timeout(module_name, monkeypatch, capsys):
    """main() evaluates timed_out rows like void/degraded -> GATE FAIL, exit 1."""
    mod = importlib.import_module(module_name)
    monkeypatch.setattr(mod, "QUERY_TIMEOUT", 0.05)
    monkeypatch.setattr(mod, "build_searcher", lambda project: _HangingSearcher())
    monkeypatch.setattr(sys, "argv", ["gate"])
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "timed out" in out
    assert "GATE FAIL" in out
