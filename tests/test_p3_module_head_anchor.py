"""P3 module-head anchors: each candidate file's head chunk enters the pool.

Root cause (probes persisted 2026-09-29 in experiments/reranker_p3/):
fresh-process direct reranker probes (BGE-M3 on :8081, holdout-style queries,
never the frozen eval-16) rank the gold module-head/docstring chunk #1 on 6/6
queries (rerank_probe_run1.json: gold_doc sigmoid 0.69-0.99; run2: module_head
top on P3/R2, all code chunks negative), while the eval code chunk scores a
negative logit (P3 -0.99, R2 -2.60 per EXPERIMENTS_LOG.md:2809) and dies at
MIN_RERANK_SCORE=0.3. The head never reaches the reranker because multi-term
RRF surfaces only a code chunk of the file.

Fix: _anchor_module_head_chunks_async — chunk_index-0 head per distinct pool
file (cached BM25 DataFrame, no new index structures), appended pre-rerank,
capped at _O1_ANCHOR_TOTAL / MAX_RERANKER_INPUT. All tests use a stub DataFrame
(no live services); live validation via scripts/p3_holdout_gate.py.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from src.config.settings import MAX_RERANKER_INPUT
from src.core.search.engine import _O1_ANCHOR_TOTAL

GOLD = "src/core/artifact_gc.py"
P3Q = "ArtifactGC _cleanup_old_projects 30d 90d 7d retention_policy"


def _pool_chunk(path, idx=5):
    return {
        "text": "def _prune_body(): ...",
        "metadata": {"file": path, "chunk_index": idx},
        "final_score": 0.01,
    }


def _df(rows):
    return pd.DataFrame(
        [
            {
                "file_path": path,
                "chunk_index": idx,
                "text": text,
                "text_full": text,
                "indexed_at": "",
                "layer": "",
            }
            for path, idx, text in rows
        ]
    )


class _FakeSearcher:
    """Minimal harness around the real P3 anchor method (stub DataFrame)."""

    def __init__(self, df):
        from src.core.search.engine import Searcher

        self._anchor = Searcher._anchor_module_head_chunks_async.__get__(self)
        self._bm25_df = df

    def _build_bm25_index(self):
        return None


def _run(coro):
    return asyncio.run(coro)


HEAD_TEXT = '"""Artifact retention policy: 30d projects 90d telemetry."""'


def test_pool_contains_gold_head_chunk():
    """P3 assertion: gold file's head chunk enters the pool pre-rerank."""
    pool = [_pool_chunk(GOLD, idx=5)]
    s = _FakeSearcher(_df([(GOLD, 0, HEAD_TEXT)]))
    out = _run(s._anchor(pool, P3Q, 5))
    files = [(r["metadata"]["file"], r["metadata"]["chunk_index"]) for r in out]
    assert (GOLD, 0) in files
    heads = [r for r in out if r.get("module_head_anchor")]
    assert len(heads) == 1 and heads[0]["metadata"]["file"] == GOLD


def test_head_already_in_pool_no_dup():
    pool = [_pool_chunk(GOLD, idx=5), _pool_chunk(GOLD, idx=0)]
    s = _FakeSearcher(_df([(GOLD, 0, HEAD_TEXT)]))
    out = _run(s._anchor(pool, P3Q, 5))
    assert len(out) == 2  # dedup by file:chunk_index — nothing appended


def test_doc_files_never_anchor():
    """Doc-guard (P2/A2): docs cite symbols without defining — no head anchor."""
    pool = [
        {"text": "# note", "metadata": {"file": "docs/NOTE.md", "chunk_index": 2},
         "final_score": 0.01},
    ]
    s = _FakeSearcher(_df([("docs/NOTE.md", 0, "# head"), (GOLD, 0, HEAD_TEXT)]))
    out = _run(s._anchor(pool, P3Q, 5))
    assert len(out) == 1  # .md file ineligible even with a head row present
    assert not [r for r in out if r.get("module_head_anchor")]


def test_data_files_never_anchor():
    pool = [_pool_chunk("src/providers/embedder/canary_set.json", idx=1)]
    s = _FakeSearcher(
        _df([("src/providers/embedder/canary_set.json", 0, "{}"), (GOLD, 0, HEAD_TEXT)])
    )
    out = _run(s._anchor(pool, P3Q, 5))
    assert out == pool  # .json ineligible


def test_total_cap_and_pool_cap():
    pool = [_pool_chunk(f"src/f{i}.py", idx=i + 1) for i in range(10)]
    s = _FakeSearcher(_df([(f"src/f{i}.py", 0, HEAD_TEXT) for i in range(10)]))
    out = _run(s._anchor(pool, P3Q, 5))
    assert len(out) <= 10 + _O1_ANCHOR_TOTAL
    assert len(out) <= MAX_RERANKER_INPUT
    keys = [(r["metadata"]["file"], r["metadata"]["chunk_index"]) for r in out]
    assert len(keys) == len(set(keys))


def test_full_pool_unchanged():
    pool = [_pool_chunk(f"src/f{i}.py", idx=1) for i in range(MAX_RERANKER_INPUT)]
    s = _FakeSearcher(_df([(f"src/f{i}.py", 0, HEAD_TEXT) for i in range(10)]))
    out = _run(s._anchor(pool, P3Q, 5))
    assert len(out) == MAX_RERANKER_INPUT  # pool cap respected


def test_limit_zero_keeps_empty_contract():
    s = _FakeSearcher(_df([(GOLD, 0, HEAD_TEXT)]))
    assert _run(s._anchor([], P3Q, 0)) == []


def test_no_head_row_degrades_to_pool():
    """File without a chunk_index-0 row: pool passes through unchanged."""
    pool = [_pool_chunk(GOLD, idx=5)]
    s = _FakeSearcher(_df([(GOLD, 3, "def x(): ...")]))
    assert _run(s._anchor(pool, P3Q, 5)) == pool


def test_no_bm25_dataframe_degrades_to_pool():
    pool = [_pool_chunk(GOLD, idx=5)]

    class _NoDf(_FakeSearcher):
        def _build_bm25_index(self):
            self._bm25_df = None

    s = _NoDf(_df([(GOLD, 0, HEAD_TEXT)]))
    assert _run(s._anchor(pool, P3Q, 5)) == pool
