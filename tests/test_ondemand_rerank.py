"""Phase 2 (E25): on-demand cosine rerank — exact math on fake vectors.

No servers, no index: embed_fn is injected. Formula pinned:
L2-normalize both sides, cosine, stable-sort desc, final_score=cosine.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.search.ondemand_rerank import (  # noqa: E402
    cosine_sims,
    rerank_by_cosine,
    split_embed_inputs,
)


def _cand(file, text):
    return {"text": text, "metadata": {"file": file}}


def test_cosine_exact():
    sims = cosine_sims([1.0, 0.0], [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    assert sims[0] == 1.0
    assert sims[1] == 0.0
    assert abs(sims[2] - math.sqrt(0.5)) < 1e-6


def test_cosine_zero_query_safe():
    assert cosine_sims([0.0, 0.0], [[1.0, 0.0]]) == [0.0]


def test_rerank_order_scores_mode_and_cut():
    cands = [_cand("a.py", "ta"), _cand("b.py", "tb"), _cand("c.py", "tc")]
    out = rerank_by_cosine(cands, [1.0, 0.0],
                           [[0.0, 1.0], [1.0, 0.0], [1.0, 1.0]], top_n=2)
    assert [c["metadata"]["file"] for c in out] == ["b.py", "c.py"]
    assert out[0]["final_score"] == 1.0
    assert all(c["metadata"]["rerank_mode"] == "ondemand_cosine" for c in out)
    # input dicts untouched (copies)
    assert "final_score" not in cands[1]


def test_rerank_stable_ties_keep_fused_order():
    cands = [_cand("a.py", "ta"), _cand("b.py", "tb")]
    out = rerank_by_cosine(cands, [1.0, 1.0], [[1.0, 0.0], [0.0, 1.0]], top_n=5)
    assert [c["metadata"]["file"] for c in out] == ["a.py", "b.py"]


def test_split_prefers_text_full_and_counts_skipped():
    cands = [
        {"text": "short", "text_full": "FULL", "metadata": {}},
        {"text": "", "metadata": {}},
        {"metadata": {}},
        {"text": "t", "metadata": {}},
    ]
    q, usable, texts, skipped = split_embed_inputs("Q", cands)
    assert q == "Q"
    assert skipped == 2
    assert texts == ["Q", "FULL", "t"]
    assert len(usable) == 2


def test_engine_wiring_present_and_flag_defaults_off():
    import os

    assert os.getenv("MSCODEBASE_ONDEMAND_RERANK", "false") == "false"
    from src.core.search import engine as E

    assert hasattr(E.Searcher, "_apply_ondemand_reranker_async")
    import inspect

    assert inspect.iscoroutinefunction(E.Searcher._apply_ondemand_reranker_async)
