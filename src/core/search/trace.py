"""
SearchTrace — Explainability Layer для search_code (v3.3.0).

Прозрачный trace каждого этапа гибридного поиска:
  Query Expansion → BM25 → Dense → RRF → MMR → Bucket → Co-change → Reranker

Использование:
    tracer = SearchTracer(query="def hybrid_search")
    results = await hybrid_search_async(..., tracer=tracer)
    trace_report = tracer.to_dict()  # или tracer.to_markdown()
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# ────────────────────────────────────────────────────────────
# Per-chunk trace entry
# ────────────────────────────────────────────────────────────

@dataclass
class ChunkTrace:
    """Трассировка одного чанка через все этапы пайплайна."""

    # Идентификация
    chunk_key: str  # "file_path:chunk_index"
    file_path: str
    chunk_index: int
    text_preview: str  # первые 80 символов

    # Этап 1-2: BM25 + Dense (сырые ранги и RRF-вклады)
    bm25_rank: Optional[int] = None
    bm25_rrf: Optional[float] = None
    dense_rank: Optional[int] = None
    dense_rrf: Optional[float] = None

    # Этап 3: RRF fusion
    rrf_total: Optional[float] = None
    rrf_position: Optional[int] = None  # позиция в RRF-результатах

    # Этап 4: MMR diversity
    mmr_lambda: Optional[float] = None
    mmr_similarity_penalty: Optional[float] = None  # max similarity к уже выбранным
    mmr_score_delta: Optional[float] = None  # изменение relative relevance
    mmr_selected: Optional[bool] = None  # True = прошёл MMR-отбор

    # Этап 5: Bucket weights
    bucket_ext: Optional[str] = None
    bucket_intent: Optional[str] = None
    bucket_weight: Optional[float] = None
    bucket_score_after: Optional[float] = None

    # Этап 6: Co-change boost
    co_change_boost: Optional[float] = None
    co_change_partners: Optional[str] = None  # какие топ-файлы вызвали буст

    # Этап 7: Multi-reranker
    reranker_score_before: Optional[float] = None
    reranker_score_after: Optional[float] = None
    reranker_applied: bool = False

    # Финальная позиция
    final_position: Optional[int] = None
    final_score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Сериализует в dict (без None значений для краткости)."""
        d = {}
        for k, v in self.__dict__.items():
            if v is not None:
                d[k] = v
        return d

    def score_breakdown_md(self) -> str:
        """Форматирует breakdown в Markdown-строку."""
        lines = []
        pos = self.final_position or "?"
        score = f"{self.final_score:.6f}" if self.final_score is not None else "N/A"
        lines.append(f"  **#{pos}** | `{self.file_path}` | score={score}")
        lines.append(f"  _Preview: {self.text_preview}..._")

        if self.bm25_rank is not None:
            lines.append(
                f"  ├─ BM25 rank={self.bm25_rank} → RRF=1/(60+{self.bm25_rank})={self.bm25_rrf:.6f}"
            )
        if self.dense_rank is not None:
            lines.append(
                f"  ├─ Dense rank={self.dense_rank} → RRF=1/(60+{self.dense_rank})={self.dense_rrf:.6f}"
            )
        if self.rrf_total is not None:
            lines.append(f"  ├─ RRF total={self.rrf_total:.6f} (pos={self.rrf_position})")

        if self.mmr_similarity_penalty is not None:
            selected = "✓ selected" if self.mmr_selected else "—"
            lines.append(
                f"  ├─ MMR penalty={self.mmr_similarity_penalty:.4f} "
                f"(λ={self.mmr_lambda}) [{selected}]"
            )

        if self.bucket_weight is not None:
            label = f"intent={self.bucket_intent}, ext={self.bucket_ext}"
            lines.append(f"  ├─ Bucket weight={self.bucket_weight} ({label})")

        if self.co_change_boost is not None and self.co_change_boost != 1.0:
            lines.append(
                f"  ├─ Co-change boost ×{self.co_change_boost} "
                f"(partners: {self.co_change_partners})"
            )

        if self.reranker_applied:
            lines.append(
                f"  └─ Reranker: {self.reranker_score_before:.6f} → {self.reranker_score_after:.6f}"
            )
        else:
            lines.append("  └─ Reranker: not applied (below top-N threshold)")

        return "\n".join(lines)


# ────────────────────────────────────────────────────────────
# Tracer — собирает данные со всего пайплайна
# ────────────────────────────────────────────────────────────

class SearchTracer:
    """Контекст трассировки поискового запроса.

    Используется как коллектор: пайплайн вызывает `record_*` методы,
    tracer сохраняет intermediate scores.

    Thread-safe для sync-этапов (BM25, bucket) через простой lock.
    """

    def __init__(self, query: str, enabled: bool = True):
        self.query = query
        self.enabled = enabled
        self._chunks: Dict[str, ChunkTrace] = {}
        self._stage_timing: Dict[str, float] = {}
        self._start_ts = time.monotonic()
        self._query_expansion_variants: List[str] = []

    # ── Context manager ──

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._stage_timing["total_ms"] = (time.monotonic() - self._start_ts) * 1000

    # ── Helpers ──

    def _key(self, chunk: dict) -> str:
        meta = chunk.get("metadata", {})
        f = meta.get("file", "?")
        ci = meta.get("chunk_index", 0)
        return f"{f}:{ci}"

    def _get_or_create(self, chunk: dict) -> ChunkTrace:
        key = self._key(chunk)
        if key not in self._chunks:
            meta = chunk.get("metadata", {})
            self._chunks[key] = ChunkTrace(
                chunk_key=key,
                file_path=meta.get("file", "?"),
                chunk_index=int(meta.get("chunk_index", 0)),
                text_preview=(chunk.get("text", "") or "")[:80],
            )
        return self._chunks[key]

    # ── Record methods (вызываются из пайплайна) ──

    def record_query_expansion(self, variants: List[str]):
        """Этап 0: варианты запроса."""
        if not self.enabled:
            return
        self._query_expansion_variants = variants

    def record_bm25_batch(self, bm25_results: List[dict]):
        """Этап 1: BM25 сырые результаты с рангами."""
        if not self.enabled:
            return
        for rank, chunk in enumerate(bm25_results, 1):
            t = self._get_or_create(chunk)
            t.bm25_rank = rank
            t.bm25_rrf = 1.0 / (60 + rank)

    def record_dense_batch(self, dense_results: List[dict]):
        """Этап 2: Dense сырые результаты с рангами."""
        if not self.enabled:
            return
        for rank, chunk in enumerate(dense_results, 1):
            t = self._get_or_create(chunk)
            t.dense_rank = rank
            t.dense_rrf = 1.0 / (60 + rank)

    def record_rrf(self, rrf_results: List[dict]):
        """Этап 3: RRF fusion — итоговые скоры."""
        if not self.enabled:
            return
        for pos, chunk in enumerate(rrf_results, 1):
            t = self._get_or_create(chunk)
            t.rrf_position = pos
            t.rrf_total = chunk.get("final_score", chunk.get("bm25_score", 0)) + \
                           chunk.get("dense_score", 0)
            # Запоминаем bm25/dense scores если они пришли из RRF
            bs = chunk.get("bm25_score")
            ds = chunk.get("dense_score")
            if bs is not None and t.bm25_rrf is None:
                t.bm25_rrf = bs
            if ds is not None and t.dense_rrf is None:
                t.dense_rrf = ds

    def record_mmr(
        self,
        chunks_before: List[dict],
        chunks_after: List[dict],
        lambda_param: float,
        similarities: Optional[Dict[str, float]] = None,
    ):
        """Этап 4: MMR diversity."""
        if not self.enabled:
            return
        for i, chunk_after in enumerate(chunks_after):
            t = self._get_or_create(chunk_after)
            t.mmr_lambda = lambda_param
            # Определяем, прошёл ли чанк MMR-отбор
            key = self._key(chunk_after)
            if similarities and key in similarities:
                t.mmr_similarity_penalty = similarities[key]
            t.mmr_selected = i < int(len(chunks_after) * 0.7)  # heuristic

    def record_bucket(
        self, chunks: List[dict], intent_hint: str
    ):
        """Этап 5: Bucket weights."""
        if not self.enabled:
            return
        for chunk in chunks:
            t = self._get_or_create(chunk)
            meta = chunk.get("metadata", {})
            fpath = meta.get("file", "")
            import os
            _, ext = os.path.splitext(fpath)
            t.bucket_ext = ext.lower()
            t.bucket_intent = intent_hint
            # Вычисляем применённый вес (дублируем логику apply_bucket_weights)
            from src.config.settings import CODE_EXTENSIONS, DOCS_EXTENSIONS, get_config
            cfg = get_config().performance
            if intent_hint == "code":
                w = cfg.code_bucket_weight * 1.2
            elif intent_hint == "docs":
                w = cfg.code_bucket_weight * 0.8
            else:
                w = cfg.code_bucket_weight
            if ext.lower() in CODE_EXTENSIONS:
                t.bucket_weight = w
            elif ext.lower() in DOCS_EXTENSIONS:
                t.bucket_weight = cfg.docs_bucket_weight if intent_hint == "auto" else \
                    cfg.docs_bucket_weight * (0.8 if intent_hint == "code" else 1.2)
            else:
                t.bucket_weight = 1.0
            t.bucket_score_after = chunk.get("final_score")

    def record_co_change(
        self, chunks: List[dict], boosts: Dict[str, float]
    ):
        """Этап 6: Co-change boost."""
        if not self.enabled:
            return
        for chunk in chunks:
            key = self._key(chunk)
            t = self._get_or_create(chunk)
            boost = boosts.get(key, 1.0)
            t.co_change_boost = boost
            if boost != 1.0:
                partners = boosts.get(f"{key}:partners", "")
                t.co_change_partners = str(partners) if partners else None

    def record_reranker(
        self, chunks_before: List[dict], chunks_after: List[dict]
    ):
        """Этап 7: Multi-provider reranker."""
        if not self.enabled:
            return
        before_scores = {}
        for ch in chunks_before:
            key = self._key(ch)
            before_scores[key] = ch.get("final_score", 0.0)
        for ch in chunks_after:
            key = self._key(ch)
            if key in before_scores:
                t = self._get_or_create(ch)
                t.reranker_score_before = before_scores[key]
                t.reranker_score_after = ch.get("final_score", t.reranker_score_before)
                t.reranker_applied = True

    def record_final(self, final_results: List[dict]):
        """Финальная позиция после всех этапов."""
        if not self.enabled:
            return
        for pos, chunk in enumerate(final_results, 1):
            t = self._get_or_create(chunk)
            t.final_position = pos
            t.final_score = chunk.get("final_score", 0.0)

    def record_stage_timing(self, stage_name: str, elapsed_ms: float):
        """Замер времени этапа."""
        if not self.enabled:
            return
        self._stage_timing[stage_name] = elapsed_ms

    # ── Output ──

    def to_dict(self) -> Dict[str, Any]:
        """Полный trace как dict (для JSON-сериализации)."""
        if not self.enabled:
            return {"enabled": False, "query": self.query}
        return {
            "query": self.query,
            "query_expansion": self._query_expansion_variants,
            "stage_timing_ms": self._stage_timing,
            "total_ms": self._stage_timing.get("total_ms", 0),
            "chunks": [ct.to_dict() for ct in sorted(
                self._chunks.values(),
                key=lambda x: (x.final_position if x.final_position is not None else 999),
            )],
        }

    def to_markdown(self, top_n: int = 5) -> str:
        """Форматирует trace как Markdown (для показа агенту/пользователю)."""
        if not self.enabled or not self._chunks:
            return "_Tracing disabled or no results_"

        lines = [
            f"### 🔍 Explain: `{self.query[:60]}`",
            f"_Pipeline stages: {len(self._stage_timing)} | "
            f"Total: {self._stage_timing.get('total_ms', 0):.0f}ms_",
            "",
        ]

        # Timing table
        lines.append("**⏱ Stage timing:**")
        for name, ms in sorted(self._stage_timing.items()):
            if name == "total_ms":
                continue
            lines.append(f"  • {name}: {ms:.0f}ms")
        lines.append("")

        # Chunk breakdowns
        sorted_chunks = sorted(
            self._chunks.values(),
            key=lambda x: (x.final_position if x.final_position is not None else 999),
        )
        lines.append(f"**📊 Score breakdown (top {top_n}):**")
        lines.append("")
        for ct in sorted_chunks[:top_n]:
            lines.append(ct.score_breakdown_md())
            lines.append("")

        return "\n".join(lines)


__all__ = [
    "ChunkTrace",
    "SearchTracer",
]
