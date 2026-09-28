"""P2 pool-entry anchors: exact-symbol chunks enter the pre-rerank pool.

Root cause (measured live 2026-09-28, fresh process + discarded warm-up):
P2 query `hybrid_search_async reciprocal_rank_fusion FTS5 BM25`, gold
src/core/search/engine.py — BM25#126, FTS#74, dense absent @200. Pool cut is
rrf_results[:limit] with raw_limit=min(limit*2,30): gold never enters at any
limit<=50. Widening to depth 126 would cost ~126x0.4s rerank (~50s) — refuted.
O1 alone cannot rescue it either: O1 candidate is `reciprocal_rank_fusion`
(df=4, strictly rarest) while gold's symbol is `hybrid_search_async`
(df=100) — no exact match, no boost (live: O1 fired on scoring.py instead).

Fix: _anchor_identifier_chunks_async — single-token FTS fetch per rare
identifier token (df<=_O1_ANCHOR_MAX_DF), exact-symbol + non-doc filter,
appended pre-rerank, capped. All tests use mocked _fts5_search_async (no live
services); live validation via scripts/o1_holdout_gate.py (fresh process).
"""

from __future__ import annotations

from src.core.search.engine import (
    _O1_ANCHOR_MAX_DF,
    _O1_ANCHOR_TOTAL,
    _is_anchor_eligible,
    _is_symbol_definition,
    _rare_identifier_tokens,
)

GOLD = "src/core/search/engine.py"
P2Q = "hybrid_search_async reciprocal_rank_fusion FTS5 BM25"


def _chunk(path, sym, idx=0, doc=False):
    meta = {"file": path, "chunk_index": idx, "symbol_name": sym}
    if doc:
        meta["file"] = "docs/NOTE.md"
    return {"text": f"def {sym}(): ...", "metadata": meta, "final_score": 0.01}


def _df_of(mapping):
    def df(t):
        return mapping.get(t, 0)

    return df


LIVE_DF = {
    "hybrid_search_async": 100,
    "reciprocal_rank_fusion": 4,
    "fts5": 140,
    "bm25": 327,
    "hybrid": 79,
    "search": 1633,
    "async": 790,
}


def test_rare_tokens_include_gold_symbol_exclude_h2_common():
    toks = _rare_identifier_tokens(P2Q, _df_of(LIVE_DF), _O1_ANCHOR_MAX_DF)
    assert "hybrid_search_async" in toks
    assert "reciprocal_rank_fusion" in toks
    assert "bm25" not in toks  # H2-collision guard (df=327)
    assert "fts5" not in toks  # common acronym (df=140)


def test_rare_tokens_single_term_empty():
    assert _rare_identifier_tokens("get_db", _df_of({"get_db": 2}), _O1_ANCHOR_MAX_DF) == []


def test_rare_tokens_no_identifiers_empty():
    assert (
        _rare_identifier_tokens("quantum computing configuration", _df_of({}), _O1_ANCHOR_MAX_DF)
        == []
    )


class _FakeSearcher:
    """Minimal harness around the real anchor method (no index needed)."""

    def __init__(self, fetched):
        from src.core.search.engine import Searcher

        self._anchor = Searcher._anchor_identifier_chunks_async.__get__(self)
        self._df = _df_of(LIVE_DF)
        self._fetched = fetched

    def _df_of(self):
        return self._df

    async def _fts5_search_async(self, query, limit=10):
        return list(self._fetched.get(query, []))


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_pool_contains_gold_p2():
    """P2 assertion: gold enters the pool via anchors even when RRF cut it."""
    gold = _chunk(GOLD, "hybrid_search_async", idx=18)
    pool = [_chunk("experiments/probe_0.txt", "probe", idx=0)]
    s = _FakeSearcher(
        {
            "hybrid_search_async": [_chunk("src/other.py", "hybrid_search_async", idx=1), gold],
            "reciprocal_rank_fusion": [
                _chunk("src/core/search/scoring.py", "reciprocal_rank_fusion", idx=0)
            ],
        }
    )
    out = _run(s._anchor(pool, P2Q, 5))
    files = [(r["metadata"]["file"], r["metadata"]["chunk_index"]) for r in out]
    assert (GOLD, 18) in files


def test_doc_chunks_never_anchor():
    pool = [_chunk("experiments/probe_0.txt", "probe", idx=0)]
    s = _FakeSearcher(
        {"hybrid_search_async": [_chunk("docs/X.md", "hybrid_search_async", idx=3, doc=True)]}
    )
    out = _run(s._anchor(pool, P2Q, 5))
    assert len(out) == 1  # doc exact-symbol match must not anchor


def test_data_files_never_anchor():
    """canary_set.json carries a bogus exact symbol (fallback scope-split) —
    data extensions are ineligible even with an exact symbol match."""
    victim = {
        "text": "def hybrid_search_async(): ...",
        "metadata": {
            "file": "src/providers/embedder/canary_set.json",
            "chunk_index": 0,
            "symbol_name": "hybrid_search_async",
        },
        "final_score": 0.04,
    }
    assert not _is_anchor_eligible(victim)
    pool = []
    s = _FakeSearcher({"hybrid_search_async": [victim]})
    assert _run(s._anchor(pool, P2Q, 5)) == []


def test_definition_outranks_caller():
    """Caller chunk listed first in FTS order, but the def chunk anchors first;
    with per-token room both enter, def first."""
    caller = {
        "text": "    await searcher.hybrid_search_async(q)",
        "metadata": {
            "file": "scripts/live_search_audit.py",
            "chunk_index": 4,
            "symbol_name": "hybrid_search_async",
        },
        "final_score": 0.05,
    }
    definition = {
        "text": "    async def hybrid_search_async(self,",
        "metadata": {"file": GOLD, "chunk_index": 18, "symbol_name": "hybrid_search_async"},
        "final_score": 0.04,
    }
    assert _is_symbol_definition(definition["text"], "hybrid_search_async")
    assert not _is_symbol_definition(caller["text"], "hybrid_search_async")
    pool = []
    s = _FakeSearcher({"hybrid_search_async": [caller, definition]})
    out = _run(s._anchor(pool, P2Q, 5))
    assert out[0]["metadata"]["file"] == GOLD
    assert (GOLD, 18) in [(r["metadata"]["file"], r["metadata"]["chunk_index"]) for r in out]


def test_substring_symbol_does_not_anchor():
    pool = []
    s = _FakeSearcher(
        {"hybrid_search_async": [_chunk("src/a.py", "my_hybrid_search_async_wide", idx=0)]}
    )
    out = _run(s._anchor(pool, P2Q, 5))
    assert out == []  # full-token equality only, never substring


def test_common_token_fetch_never_anchored_even_if_exact():
    """H2-collision: even if FTS returned an exact match for a common token,
    the rarity cap excludes the token before any fetch."""
    pool = []
    s = _FakeSearcher({"bm25": [_chunk("src/core/search/bm25.py", "bm25", idx=0)]})
    out = _run(s._anchor(pool, P2Q, 5))
    assert out == []  # 'bm25' df=327 > cap: no fetch, no anchor


def test_total_cap_and_dedup():
    pool = [_chunk(GOLD, "hybrid_search_async", idx=18)]
    many = [_chunk(f"src/f{i}.py", "hybrid_search_async", idx=i) for i in range(10)]
    s = _FakeSearcher(
        {
            "hybrid_search_async": many,
            "reciprocal_rank_fusion": [
                _chunk("src/core/search/scoring.py", "reciprocal_rank_fusion", idx=0)
            ],
        }
    )
    out = _run(s._anchor(pool, P2Q, 5))
    assert len(out) <= 1 + _O1_ANCHOR_TOTAL
    keys = [(r["metadata"]["file"], r["metadata"]["chunk_index"]) for r in out]
    assert len(keys) == len(set(keys))


def test_limit_zero_keeps_empty_contract():
    s = _FakeSearcher({"hybrid_search_async": [_chunk(GOLD, "hybrid_search_async", idx=18)]})
    assert _run(s._anchor([], P2Q, 0)) == []


def test_fts_failure_degrades_to_pool():
    pool = [_chunk("experiments/probe_0.txt", "probe", idx=0)]

    class _Broken(_FakeSearcher):
        async def _fts5_search_async(self, query, limit=10):
            raise RuntimeError("fts down")

    s = _Broken({})
    assert _run(s._anchor(pool, P2Q, 5)) == pool


def test_no_bm25_stats_degrades_to_pool():
    pool = [_chunk("experiments/probe_0.txt", "probe", idx=0)]

    class _NoStats(_FakeSearcher):
        def _df_of(self):
            return None

    s = _NoStats({})
    assert _run(s._anchor(pool, P2Q, 5)) == pool
