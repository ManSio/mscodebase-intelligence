"""Per-call control of the on-demand cosine rerank (2026-11-09).

Owner decision: the fast path is the default, and the agent opts into reranking
per call. These tests pin three properties that a shared mutable flag would
break: the config default is off, an explicit value overrides it, and two
concurrent calls with opposite values do not change each other.
"""

import asyncio
from types import SimpleNamespace

from src.config.settings import SearchConfig
from src.core.search.engine import Searcher


def test_config_default_is_off(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_ONDEMAND_RERANK", raising=False)
    assert SearchConfig().ondemand_rerank is False


def test_env_still_enables_it(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_ONDEMAND_RERANK", "true")
    assert SearchConfig().ondemand_rerank is True


def _searcher(configured: bool) -> Searcher:
    searcher = Searcher.__new__(Searcher)  # bypass __init__: only the branch matters
    searcher.indexer = SimpleNamespace(table=None, db_manager=None)
    searcher._chunk_store = SimpleNamespace(count=lambda: 1)
    searcher._dense_off = True
    searcher._ondemand_rerank = configured
    return searcher


def test_resolution_none_uses_config_true():
    assert _searcher(True)._resolve_ondemand_rerank(None) is True


def test_resolution_none_uses_config_false():
    assert _searcher(False)._resolve_ondemand_rerank(None) is False


def test_resolution_explicit_false_wins_over_config_true():
    assert _searcher(True)._resolve_ondemand_rerank(False) is False


def test_resolution_explicit_true_wins_over_config_false():
    assert _searcher(False)._resolve_ondemand_rerank(True) is True


def test_sqlite_path_receives_the_per_call_value(monkeypatch):
    seen = {}

    async def fake_sqlite(self, query, limit, layer=None, tracer=None, rerank=None):
        seen["rerank"] = rerank
        return []

    monkeypatch.setattr(Searcher, "_sqlite_hybrid_search_async", fake_sqlite)
    searcher = _searcher(False)

    result = asyncio.run(searcher.hybrid_search_async("q", limit=5, rerank=True))

    assert result == []
    assert seen["rerank"] is True
    assert searcher._ondemand_rerank is False  # override must not stick


def test_concurrent_calls_do_not_share_the_flag(monkeypatch):
    seen = {}

    async def fake_sqlite(self, query, limit, layer=None, tracer=None, rerank=None):
        await asyncio.sleep(0)
        seen[query] = rerank
        return []

    monkeypatch.setattr(Searcher, "_sqlite_hybrid_search_async", fake_sqlite)
    searcher = _searcher(False)
    flags = [True, False, True, False, True, False, True, False]

    async def run_all():
        return await asyncio.gather(
            *(
                searcher.hybrid_search_async(f"q{i}", limit=5, rerank=flag)
                for i, flag in enumerate(flags)
            )
        )

    asyncio.run(run_all())

    assert [seen[f"q{i}"] for i in range(len(flags))] == flags
    assert searcher._ondemand_rerank is False


class _Store:
    """Minimal chunk store: enough for the real _sqlite_hybrid_search_async."""

    def count(self):
        return 2

    def search(self, query, limit):
        return [
            {"text": "alpha", "text_full": "alpha", "final_score": 1.0,
             "metadata": {"file": "a.py", "chunk_index": 0}},
            {"text": "beta", "text_full": "beta", "final_score": 0.5,
             "metadata": {"file": "b.py", "chunk_index": 0}},
        ]


def _sqlite_searcher(configured: bool) -> Searcher:
    searcher = Searcher.__new__(Searcher)
    searcher._ondemand_rerank = configured
    searcher._ondemand_rerank_top_n = 10
    searcher._ondemand_rerank_max_chars = 1600
    searcher._chunk_store = _Store()
    searcher._last_rerank_timing = {}
    return searcher


def test_real_sqlite_branch_skips_rerank_when_called_with_false(monkeypatch):
    calls = []

    async def fake_rerank(self, query, pool, limit):
        calls.append(query)
        return pool

    monkeypatch.setattr(Searcher, "_apply_ondemand_reranker_async", fake_rerank)
    searcher = _sqlite_searcher(configured=True)  # config says yes

    rows = asyncio.run(
        searcher._sqlite_hybrid_search_async("plain words here", 5, rerank=False)
    )

    assert rows, "candidates must still be returned"
    assert calls == [], "rerank=False must beat the configured true"


def test_real_sqlite_branch_reranks_when_called_with_true(monkeypatch):
    calls = []

    async def fake_rerank(self, query, pool, limit):
        calls.append(query)
        return pool

    monkeypatch.setattr(Searcher, "_apply_ondemand_reranker_async", fake_rerank)
    searcher = _sqlite_searcher(configured=False)  # config says no

    asyncio.run(
        searcher._sqlite_hybrid_search_async("plain words here", 5, rerank=True)
    )

    assert calls == ["plain words here"]
