"""P2 pre-rerank pool + threshold/top-N selection + holdout calibration.

P2 (root cause, verified by code reading, engine.py/scoring.py):
`hybrid_search_async` fuses tiers with 3-way RRF and then amputates the
pre-rerank pool with ``rrf_results[:limit]`` (engine.py). RRF rewards
multi-tier consensus: a target found by ONE tier only (P2: BM25 rank 0 for
``src/core/search/engine.py``) scores ``1/(60+1)`` while junk present in 2-3
tiers at mediocre ranks accumulates 2-3x that. The ``[:limit]`` cut then drops
the single-tier winner before the reranker ever sees it. MMR is innocent
(reorder-only, no drops), bucket weights favour the target (.py=1.0 vs
.txt/.md=0.5), query expansion keeps the verbatim query as variants[0] —
so the standalone-BM25-rank-0 vs hybrid-loss "contradiction" is exactly this
fusion dilution, not a retrieval miss.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.core.search.scoring import anchor_tier_winners, reciprocal_rank_fusion_3way, rrf_key
from src.providers.reranker.multi_provider import MultiProviderReranker
from src.providers.reranker.threshold_calibration import calibrate_threshold

TARGET_FILE = "src/core/search/engine.py"


def _chunk(path: str, idx: int = 0) -> dict:
    return {
        "text": f"chunk of {path}",
        "metadata": {"file": path, "chunk_index": idx},
    }


def _p2_tiers():
    """Synthetic P2: BM25 winner + multi-tier junk (mirrors the polluted
    index: experiments/**/*.txt share the generic P2 query terms)."""
    target = _chunk(TARGET_FILE, 5)
    junk = [_chunk(f"experiments/probe_{i}.txt", 0) for i in range(12)]
    bm25 = [target] + [_chunk(f"experiments/probe_{i}.txt", 0) for i in range(12)]
    bm25 += [_chunk(f"experiments/filler_{i}.txt", 0) for i in range(7)]
    dense = list(junk) + [_chunk(f"src/unrelated_{i}.py", 0) for i in range(8)]
    fts5 = list(junk) + [_chunk(f"docs/note_{i}.md", 0) for i in range(8)]
    return target, bm25, dense, fts5


def _pool_keys(pool) -> list:
    return [c["metadata"]["file"] for c in pool]


def _assemble_pool(rrf, tiers, limit, pool_cap=30):
    """Pool assembly как в engine.hybrid_search_async (RRF-порядок; engine
    дополнительно сохраняет MMR-порядок базы — якоря только в хвосте)."""
    return anchor_tier_winners(
        rrf, tiers, limit, per_tier=1, pool_cap=pool_cap
    )


def test_p2_bm25_winner_survives_pre_rerank_pool():
    """P2 regression: single-tier BM25 rank-0 target must enter the pool."""
    target, bm25, dense, fts5 = _p2_tiers()
    limit, raw_limit = 10, 20
    rrf = reciprocal_rank_fusion_3way(bm25, dense, fts5, raw_limit)
    # Старый срез rrf[:limit] цель ампутировал (тест падал до фикса);
    # сборка с якорями обязана её вернуть.
    assert TARGET_FILE not in _pool_keys(rrf[:limit])
    pool = _assemble_pool(
        rrf,
        [(bm25, "bm25_score"), (dense, "dense_score"), (fts5, "fts5_score")],
        limit,
    )
    assert TARGET_FILE in _pool_keys(pool), (
        "P2: BM25 rank-0 target missing even with tier anchors "
        f"(pool={_pool_keys(pool)})"
    )


def test_anchor_preserves_rrf_order_and_dedupes():
    target, bm25, dense, fts5 = _p2_tiers()
    rrf = reciprocal_rank_fusion_3way(bm25, dense, fts5, 20)
    pool = _assemble_pool(
        rrf,
        [(bm25, "bm25_score"), (dense, "dense_score"), (fts5, "fts5_score")],
        10,
    )
    base_keys = [rrf_key(c) for c in rrf[:10]]
    assert [rrf_key(c) for c in pool[:10]] == base_keys
    assert len({rrf_key(c) for c in pool}) == len(pool)


def test_anchor_pool_cap_respected():
    target, bm25, dense, fts5 = _p2_tiers()
    rrf = reciprocal_rank_fusion_3way(bm25, dense, fts5, 20)
    pool = _assemble_pool(
        rrf,
        [(bm25, "bm25_score"), (dense, "dense_score"), (fts5, "fts5_score")],
        10,
        pool_cap=11,
    )
    assert len(pool) <= 11


def test_anchor_empty_pool_for_zero_limit():
    """Контракт hybrid_search_async: limit=0 -> пустой пул (якоря не воскрешают)."""
    target, bm25, dense, fts5 = _p2_tiers()
    rrf = reciprocal_rank_fusion_3way(bm25, dense, fts5, 20)
    assert _assemble_pool(rrf, [(bm25, "bm25_score")], 0) == []


def test_anchor_reconstructs_winner_outside_rrf_list():
    """Лидер тира вне RRF-списка: fused-запись строится из тир-элемента."""
    ghost = _chunk("src/ghost.py", 0)
    rrf = [_chunk(f"src/other_{i}.py", 0) for i in range(5)]
    for i, c in enumerate(rrf):
        c.update(
            {"bm25_score": 0.0, "dense_score": 0.0, "fts5_score": 0.0,
             "graph_score": 0.0, "final_score": 0.05 - i * 0.001}
        )
    pool = anchor_tier_winners(
        rrf, [([ghost], "bm25_score")], 5, per_tier=1, pool_cap=30
    )
    keys = [rrf_key(c) for c in pool]
    assert "src/ghost.py:0" in keys
    entry = pool[keys.index("src/ghost.py:0")]
    assert entry["bm25_score"] == entry["final_score"] > 0.0


# ── Top-N recall floor (MAX_RERANKER_TOPN) ─────────────────────────────


def _llama_reranker_with(logits):
    r = MultiProviderReranker()
    r.ollama_available = False
    r.lm_studio_available = False
    r.llama_cpp_available = True
    r._llama_cpp_rerank = AsyncMock(return_value=list(logits))
    return r


def _p3_chunks():
    """Пул из замера 2026-09-27: 10 чанков, цель P3 — логит -0.99 (0.271)."""
    return [
        {"text": f"chunk {i}", "metadata": {"file": f"src/f{i}.py", "chunk_index": 0}}
        for i in range(10)
    ]


@pytest.mark.asyncio
async def test_topn_disabled_preserves_current_behavior():
    """Default MAX_RERANKER_TOPN=0: P3-цель (0.271<0.3) отсекается, как раньше."""
    reranker = _llama_reranker_with(
        [1.65, 0.75, -0.20, -0.99, -2.95, -5.55, -6.88, -8.08, -8.25, -9.38]
    )
    with patch(
        "src.providers.reranker.multi_provider.get_config"
    ) as cfg:
        cfg.return_value.performance.reranker_topn_keep = 0
        result = await reranker.rerank("q", _p3_chunks(), top_n=10)
    scores = [c["reranker_score"] for c in result]
    assert all(s >= 0.3 for s in scores)
    # проходят 1.65->0.839, 0.75->0.679, -0.20->0.450; цель P3 (-0.99->0.271)
    # и хвост отсечены — поведение до adopt-ветки
    assert len(result) == 3


@pytest.mark.asyncio
async def test_topn_floor_returns_p3_target():
    """MAX_RERANKER_TOPN=4: union порога с top-4 возвращает цель P3
    (-0.99->0.271 — 4-я по скору, отсекалась абсолютным порогом)."""
    reranker = _llama_reranker_with(
        [1.65, 0.75, -0.20, -0.99, -2.95, -5.55, -6.88, -8.08, -8.25, -9.38]
    )
    with patch(
        "src.providers.reranker.multi_provider.get_config"
    ) as cfg:
        cfg.return_value.performance.reranker_topn_keep = 4
        result = await reranker.rerank("q", _p3_chunks(), top_n=10)
    assert len(result) == 4
    assert [c["reranker_score"] for c in result] == sorted(
        [c["reranker_score"] for c in result], reverse=True
    )
    # 4-я — цель P3 (sigmoid(-0.99)≈0.271), отсекавшаяся порогом
    assert result[3]["reranker_score"] == pytest.approx(0.271, rel=1e-3)


@pytest.mark.asyncio
async def test_topn_floor_never_exceeds_top_n():
    reranker = _llama_reranker_with([5.0, 4.0, 3.0])
    chunks = _p3_chunks()[:3]
    with patch(
        "src.providers.reranker.multi_provider.get_config"
    ) as cfg:
        cfg.return_value.performance.reranker_topn_keep = 100
        result = await reranker.rerank("q", chunks, top_n=2)
    assert len(result) <= 2


# ── Holdout-калибровка + анти-перебор ──────────────────────────────────


def test_calibration_selects_f1_maximum_on_holdout():
    scores = [0.9, 0.8, 0.5, 0.35, 0.2, 0.1]
    labels = [True, True, False, True, False, False]
    # t=0.35: P=3/4 R=1.0 F1=0.857 (максимум); t=0.5: F1=0.667; t=0.8: F1=0.8
    t = calibrate_threshold(scores, labels, source="holdout-2026-10-03")
    assert t == pytest.approx(0.35)


def test_calibration_tie_prefers_higher_threshold():
    scores = [0.9, 0.8, 0.1]
    labels = [True, False, False]
    # t=0.9: P=1 R=1 F1=1.0; t<=0.8: P<=0.5 — максимум единственный
    assert calibrate_threshold(scores, labels, source="holdout-A") == pytest.approx(0.9)


@pytest.mark.parametrize(
    "source", ["eval", "Evaluation", "frozen", "frozen-eval", "token_reduction_v3", "v3"]
)
def test_calibration_refuses_eval_source(source):
    """Анти-перебор как тест: калибровка на eval запрещена кодом, не словом."""
    with pytest.raises(ValueError, match="[Кк]алибровка"):
        calibrate_threshold([0.9, 0.1], [True, False], source=source)


def test_calibration_accepts_holdout_source():
    t = calibrate_threshold([0.9, 0.1], [True, False], source="holdout-batch-1")
    assert t == pytest.approx(0.9)


def test_calibration_rejects_empty_and_labelless():
    with pytest.raises(ValueError):
        calibrate_threshold([], [], source="holdout-A")
    with pytest.raises(ValueError):
        calibrate_threshold([0.5], [False], source="holdout-A")
