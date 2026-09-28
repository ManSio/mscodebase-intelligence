"""O1 rare-identifier boost: unit tests (spec items 1-3, 5).

Covers:
- extraction of identifier-shaped tokens (snake/CamelCase/Pascal/CONSTANT/--flag);
- D1 rarity gate incl. H2-style collision (common identifier-shaped term -> None);
- D2 exact gate (full-token equality only, never substring) + doc-guard control;
- D3 pre-rerank pool assertion (gold in pool pre-boost, first post-boost, x100).
"""
from unittest.mock import MagicMock

from src.core.search.engine import (
    Searcher,
    _boost_rare_identifier,
    _extract_identifier_tokens,
    _identifier_exact_match,
    _pick_rare_identifier,
)


def _chunk(symbol=None, text=None, score=1.0, fname="src/core/search/engine.py"):
    return {
        "text": text if text is not None else f"async def {symbol}(): ...",
        "metadata": {"file": fname, "chunk_index": 0, **(
            {"symbol_name": symbol} if symbol else {})},
        "final_score": score,
    }


def _doc_chunk(symbol):
    return {
        "text": f"class {symbol} described here",
        "metadata": {"file": "KNOWN_ISSUES.md", "chunk_index": 0,
                     "symbol_name": symbol},
        "final_score": 5.0,
    }


# --- extraction (spec 1) ---
def test_extract_shapes():
    toks = _extract_identifier_tokens(
        "how does hybrid_search_async handle CamelCase PascalCase FTS5 --max-tokens query")
    assert "hybrid_search_async" in toks
    assert "CamelCase" in toks
    assert "PascalCase" in toks
    assert "FTS5" in toks
    assert "--max-tokens" in toks


def test_extract_plain_words_ignored():
    assert _extract_identifier_tokens("how does search handle query") == []


# --- D1 rarity gate (spec 1) ---
def test_pick_rarest_identifier():
    df = {"hybrid_search_async": 2, "search": 50, "query": 40, "how": 90}
    assert _pick_rare_identifier(
        "how hybrid_search_async search query", df.get) == "hybrid_search_async"


def test_collision_common_term_no_boost_h2():
    """H2-style: identifier-shaped `BM25` is common in index -> must NOT boost."""
    df = {"bm25": 80, "search": 50, "hybrid_search_async": 2, "query": 40}
    # BM25 itself is not the rarest -> None for a BM25-anchored query...
    assert _pick_rare_identifier("BM25 search query", df.get) is None
    # ...and a query where the only identifier is common also yields None.
    assert _pick_rare_identifier(
        "BM25 search query hybrid", {**df, "hybrid": 90}.get) is None


def test_tie_for_rarest_no_boost():
    df = {"hybrid_search_async": 5, "reciprocal_rank_fusion": 5, "query": 40}
    assert _pick_rare_identifier(
        "hybrid_search_async reciprocal_rank_fusion query", df.get) is None


def test_single_term_query_no_pick():
    assert _pick_rare_identifier("hybrid_search_async", {"hybrid_search_async": 1}.get) is None


# --- D2 exact gate (spec 2) ---
def test_exact_match_boosts_code_chunk():
    pool = [_chunk("other_func", score=9.0),
            _chunk("hybrid_search_async", score=1.0)]
    out = _boost_rare_identifier(pool, "hybrid_search_async")
    assert out[0]["metadata"].get("symbol_name") == "hybrid_search_async"
    assert out[0]["identifier_boost"] is True
    assert out[0]["final_score"] == 1.0 * 100.0  # proven x100 convention


def test_substring_never_boosts():
    pool = [_chunk("my_hybrid_search_async_wrapper", score=9.0)]
    out = _boost_rare_identifier(pool, "hybrid_search_async")
    assert all("identifier_boost" not in r for r in out)


def test_doc_chunk_citing_identifier_not_boosted():
    """Negative control: doc chunk citing the identifier is NOT boosted."""
    pool = [_doc_chunk("hybrid_search_async"),
            _chunk("unrelated", score=1.0)]
    out = _boost_rare_identifier(pool, "hybrid_search_async")
    assert all("identifier_boost" not in r for r in out)
    assert out[0]["metadata"]["file"] == "KNOWN_ISSUES.md"  # order untouched


def test_identifier_exact_match_helper():
    assert _identifier_exact_match(_chunk("hybrid_search_async"), "hybrid_search_async")
    assert not _identifier_exact_match(
        _chunk("my_hybrid_search_async_wrapper"), "hybrid_search_async")
    assert not _identifier_exact_match(
        _doc_chunk("hybrid_search_async"), "hybrid_search_async")


# --- D3 pre-rerank pool (spec 3) ---
def test_pre_rerank_pool_assertion_gold_survives():
    """Gold is deep in the pool pre-boost; O1 brings it to front pre-reranker."""
    pool = [_chunk(f"noise_{i}", score=10.0 - i) for i in range(8)]
    gold = _chunk("hybrid_search_async", score=0.5)
    pool.append(gold)
    assert gold in pool  # gold in pool PRE-boost (acceptance criterion)
    out = _boost_rare_identifier(pool, "hybrid_search_async")
    assert out[0] is gold


def test_searcher_method_end_to_end_with_fake_bm25():
    s = Searcher(MagicMock(), MagicMock())
    s._build_bm25_index = lambda: None  # avoid real index build
    # Fake BM25 stats: candidate rare, rest common.
    s._bm25 = {
        "a.py:0": {"hybrid_search_async": 1.0, "query": 1.0},
        "b.py:0": {"query": 1.0, "search": 1.0},
        "c.py:0": {"query": 1.0, "search": 1.0, "bm25": 1.0},
    }
    pool = [_chunk("search", score=9.0),
            _chunk("hybrid_search_async", score=1.0)]
    out = s._apply_o1_identifier_boost(
        pool, "hybrid_search_async search query")
    assert out[0]["metadata"].get("symbol_name") == "hybrid_search_async"
    assert out[0]["identifier_boost"] is True


def test_searcher_method_no_bm25_degrades_cleanly():
    s = Searcher(MagicMock(), MagicMock())
    s._build_bm25_index = lambda: None
    s._bm25 = {}
    pool = [_chunk("hybrid_search_async", score=1.0)]
    assert s._apply_o1_identifier_boost(pool, "hybrid_search_async query") == pool
