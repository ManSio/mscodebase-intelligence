"""Scoring and boosting functions extracted from engine.py.

Contains:
- `reciprocal_rank_fusion` — RRF merge of BM25 + dense results
- `apply_bucket_weights` — soft weighting by file extension / intent
- `_apply_co_change_boost` — git co-change coupling boost (uses `self`)
"""

import logging
import os
from typing import List

from src.core.config import CODE_EXTENSIONS, DOCS_EXTENSIONS, get_config

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    bm25_results: List[dict],
    dense_results: List[dict],
    limit: int = 5,
    rrf_k: int = 60,
) -> List[dict]:
    """Reciprocal Rank Fusion (RRF) для объединения BM25 и dense результатов.

    Формула: rrf_score(d) = Σ 1/(k + rank_i(d))
    RRF устойчив к разным масштабам скоров и не требует нормализации.

    Args:
        bm25_results: Результаты BM25 поиска
        dense_results: Результаты векторного поиска
        limit: Максимальное число результатов
        rrf_k: Константа RRF (обычно 60), сглаживает вклад рангов
    """
    scores: dict = {}
    results_map: dict = {}

    # BM25 ранги
    for rank, result in enumerate(bm25_results, 1):
        key = f"{result['metadata']['file']}:{result['metadata']['chunk_index']}"
        scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
        if key not in results_map:
            results_map[key] = {
                **result,
                "bm25_score": 1.0 / (rrf_k + rank),
                "dense_score": 0.0,
            }
        else:
            results_map[key]["bm25_score"] = 1.0 / (rrf_k + rank)

    # Dense ранги
    for rank, result in enumerate(dense_results, 1):
        key = f"{result['metadata']['file']}:{result['metadata']['chunk_index']}"
        scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
        if key not in results_map:
            results_map[key] = {
                **result,
                "bm25_score": 0.0,
                "dense_score": 1.0 / (rrf_k + rank),
            }
        else:
            results_map[key]["dense_score"] = 1.0 / (rrf_k + rank)

    # Сортировка по RRF скору
    sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[:limit]

    results = []
    for key in sorted_keys:
        result = results_map[key]
        results.append(
            {
                "text": result["text"],
                "metadata": result["metadata"],
                "bm25_score": result["bm25_score"],
                "dense_score": result["dense_score"],
                "final_score": scores[key],
            }
        )

    return results


def apply_bucket_weights(
    chunks: List[dict],
    intent_hint: str = "auto",
) -> List[dict]:
    """Применяет soft weighting к чанкам на основе intent_hint и расширения файла.

    Args:
        chunks: Список чанков-словарей с metadata.file и final_score
        intent_hint: "auto" (нейтрально), "code" (буст кода), "docs" (буст доков)

    Returns:
        Тот же список с изменёнными final_score (in-place + return)
    """
    perf_config = get_config().performance
    base_code_w = perf_config.code_bucket_weight
    base_docs_w = perf_config.docs_bucket_weight

    # intent_hint накладывается поверх базовых весов из .env
    if intent_hint == "code":
        code_w, docs_w = base_code_w * 1.2, base_docs_w * 0.8
    elif intent_hint == "docs":
        code_w, docs_w = base_code_w * 0.8, base_docs_w * 1.2
    else:
        code_w, docs_w = base_code_w, base_docs_w

    for chunk in chunks:
        metadata = chunk.get("metadata")
        if not isinstance(metadata, dict):
            continue
        file_path_str = metadata.get("file", "")
        if not file_path_str or not isinstance(file_path_str, str):
            continue

        # Защита от UNC-префикса \\?\ и пустых/относительных путей:
        # os.path.splitext работает со строками и не делает resolve().
        clean_path = file_path_str
        if clean_path.startswith("\\\\?\\"):
            clean_path = clean_path[4:]
        _, ext = os.path.splitext(clean_path)
        ext = ext.lower()

        if ext in CODE_EXTENSIONS:
            chunk["final_score"] = chunk.get("final_score", 0.0) * code_w
        elif ext in DOCS_EXTENSIONS:
            chunk["final_score"] = chunk.get("final_score", 0.0) * docs_w

    return chunks


def _apply_co_change_boost(self, chunks: List[dict]) -> List[dict]:
    """v3.0: Бустит файлы, которые часто меняются вместе с топ-результатами.

    Использует CommitMemory для вычисления co-change coupling.
    Формула: если файл B часто меняется вместе с файлом A (coupling >= 0.3),
    и A в топ-3 результатах — B получает множитель ×1.15.

    Note:
        This function is designed to be assigned as a method on Searcher
        (it uses `self` to access `_co_change_matrix` and `self.indexer`).
    """
    if len(chunks) <= 1:
        return chunks

    # Собираем имена файлов из топ-3 результатов
    top_files: set = set()
    for i, chunk in enumerate(chunks[:3]):
        meta = chunk.get("metadata")
        if isinstance(meta, dict):
            f = meta.get("file", "")
            if f:
                top_files.add(f)
    if not top_files:
        return chunks

    # Загружаем co-change матрицу (лениво, с кэшем на инстансе)
    co_matrix = getattr(self, "_co_change_matrix", None)
    if co_matrix is None:
        try:
            from src.core.commit_memory import CommitMemory

            project_path = getattr(self.indexer, "project_path", None)
            if project_path is not None:
                cm = CommitMemory(project_path)
                co_matrix = cm.compute_co_change_matrix(min_co_changes=3)
                self._co_change_matrix = co_matrix
        except Exception as e:
            logger.debug(f"Co-change matrix unavailable: {e}")
            self._co_change_matrix = {}
            return chunks

    if not co_matrix:
        return chunks

    # Применяем boost
    for chunk in chunks:
        meta = chunk.get("metadata")
        if not isinstance(meta, dict):
            continue
        file_path = meta.get("file", "")
        if file_path in co_matrix:
            partners = co_matrix[file_path]
            # Если хотя бы один партнёр в топ-файлах — бустим
            if partners and any(tf in partners for tf in top_files):
                best_coupling = max(partners.get(tf, 0) for tf in top_files)
                chunk["final_score"] = chunk.get("final_score", 0.0) * (
                    1.0 + best_coupling * 0.3
                )

    return chunks
