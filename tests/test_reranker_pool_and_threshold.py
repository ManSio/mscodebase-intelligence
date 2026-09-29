"""Reranker top-N recall floor + holdout threshold calibration.

Salvaged from PR #52 (non-conflicting part): tier-winner anchors were
skipped — P2 is covered by merged #54 (_anchor_identifier_chunks_async)
at the same pool site; a second P2 mechanism needs its own A/B.

- Top-N floor (MAX_RERANKER_TOPN, default 0 = off): union of threshold
  passers with top-N by score. P3 precedent: target 0.271<0.3 cut by the
  absolute threshold returns as 4th by score with top_n_keep>=3.
- Holdout calibration: F1-max threshold selection; eval sources rejected
  by code (ValueError), not by comment.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.providers.reranker.multi_provider import MultiProviderReranker
from src.providers.reranker.threshold_calibration import calibrate_threshold

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
