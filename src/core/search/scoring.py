"""Scoring and boosting functions extracted from engine.py.

Contains:
- `reciprocal_rank_fusion` — RRF merge of BM25 + dense results
- `apply_bucket_weights` — soft weighting by file extension / intent
- `_apply_co_change_boost` — git co-change coupling boost (uses `self`)
"""

import logging
import os
import re
from typing import List, Optional

import numpy as np

from src.config.settings import CODE_EXTENSIONS, DOCS_EXTENSIONS, get_config

__all__ = [
    "reciprocal_rank_fusion",
    "auto_detect_intent",
    "apply_bucket_weights",
    "apply_mmr_diversity",
]
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


def auto_detect_intent(query: str) -> str:
    """Авто-определение intent по тексту запроса (v3.2.1 B1).

    Keyword-based эвристики: анализирует запрос и определяет,
    ищет пользователь код, документацию или архитектуру.

    Args:
        query: Поисковый запрос

    Returns:
        "code", "docs" или "auto"
    """
    if not query:
        return "auto"
    q = query.lower()

    # Сигналы кода: определения, классы, функции, типы
    code_signals = [
        r'\bdef\b', r'\bclass\b', r'\bfunc\b', r'\bfn\b',
        r'\bimport\b', r'\bfrom\b', r'\breturn\b', r'\basync\b',
        r'\bawait\b', r'\btype\b', r'\binterface\b', r'\bimpl\b',
        r'\benum\b', r'\bstruct\b', r'\bconst\b', r'\blet\b',
        r'\bvar\b', r'\bλ\b', r'\blambda\b',
        r'^def ', r'^class ', r'^async def ',
        r'::', r'->',  # type hints
    ]
    code_score = sum(1 for p in code_signals if re.search(p, q))

    # Сигналы документации: readme, docs, help, guide
    docs_signals = [
        r'\bdoc\b', r'\bdocs\b', r'\breadme\b', r'\bhelp\b',
        r'\bguide\b', r'\btutorial\b', r'\bexample\b', r'\busage\b',
        r'\binstall\b', r'\bhow to\b', r'\bwhat is\b',
        r'\.md$', r'\.rst$', r'readme', r'changelog', r'license',
    ]
    docs_score = sum(1 for p in docs_signals if re.search(p, q))

    # Сигналы архитектуры: layer, module, arch, component
    arch_signals = [
        r'\barch\b', r'\barchitecture\b', r'\blayer\b',
        r'\bmodule\b', r'\bcomponent\b', r'\bdependency\b',
        r'\bcoupling\b', r'\bdiagram\b', r'\bflow\b',
        r'\bpattern\b', r'\bdesign\b', r'\bstructure\b',
    ]
    arch_score = sum(1 for p in arch_signals if re.search(p, q))

    # Если архитектурных сигналов больше всего — docs (схемы/диаграммы)
    # Иначе — выбираем между code и docs
    if arch_score >= code_score and arch_score >= docs_score and arch_score >= 2:
        return "docs"
    if code_score > docs_score:
        return "code"
    if docs_score > code_score:
        return "docs"

    return "auto"


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


def apply_mmr_diversity(
    chunks: List[dict],
    query_vector: Optional[list] = None,
    lambda_param: float = 0.6,
    top_k: int = 10,
) -> List[dict]:
    """MMR-диверсификация: убирает дубли, сохраняя релевантность.

    v3.2.1: Применяется после RRF, перед bucket weights.
    Использует dense vectors из LanceDB для расчёта разнообразия.

    Args:
        chunks: Результаты после RRF (с полем "vector" для dense-результатов)
        query_vector: Вектор запроса (если None — MMR пропускается)
        lambda_param: Баланс (0=max diversity, 1=max relevance)
        top_k: Сколько результатов диверсифицировать (остальные — по relevance)

    Returns:
        Тот же список с пересортированными final_score (in-place + return)
    """
    if not chunks or query_vector is None or lambda_param >= 1.0:
        return chunks

    n = len(chunks)
    if n <= 1:
        return chunks

    # Собираем векторы (только те, у кого есть vector)
    vecs = []
    idx_map = []  # индекс в chunks → позиция в vecs
    for i, ch in enumerate(chunks):
        v = ch.get("vector")
        if v is not None and isinstance(v, (list, np.ndarray)):
            vecs.append(np.asarray(v, dtype=np.float32))
            idx_map.append(i)

    if len(vecs) < 2:
        # Недостаточно векторов — возвращаем как есть
        return chunks

    vecs = np.stack(vecs)
    # Нормализуем
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1
    vecs = vecs / norms

    query_vec = np.asarray(query_vector, dtype=np.float32)
    q_norm = np.linalg.norm(query_vec)
    if q_norm > 0:
        query_vec = query_vec / q_norm

    # Relevance scores (cosine similarity с запросом)
    relevance = vecs @ query_vec
    # Нормализуем relevance в [0, 1]
    if relevance.max() > relevance.min():
        relevance = (relevance - relevance.min()) / (relevance.max() - relevance.min())
    else:
        relevance = np.ones_like(relevance) * 0.5

    # MMR greedy selection
    selected_mask = np.zeros(len(vecs), dtype=bool)
    selected_order = []

    # Первый — самый релевантный
    first = int(relevance.argmax())
    selected_mask[first] = True
    selected_order.append(idx_map[first])

    for _ in range(min(top_k - 1, len(vecs) - 1)):
        candidates = np.where(~selected_mask)[0]
        if len(candidates) == 0:
            break

        sim_to_selected = vecs[candidates] @ vecs[selected_mask].T
        max_sim = sim_to_selected.max(axis=1) if sim_to_selected.shape[1] > 0 else np.zeros(len(candidates))

        mmr = lambda_param * relevance[candidates] - (1 - lambda_param) * max_sim
        best = candidates[int(mmr.argmax())]

        selected_mask[best] = True
        selected_order.append(idx_map[best])

    # Добавляем оставшиеся (те, что не прошли MMR) в порядке relevance
    remaining = [i for i in range(n) if i not in selected_order]
    final_order = selected_order + remaining

    # Пересортировываем chunks
    reordered = [chunks[i] for i in final_order]

    # Обновляем final_score с учётом MMR
    for pos, (i, orig_i) in enumerate(zip(range(n), final_order)):
        if pos < len(selected_order):
            # MMR-отобранные получают boost
            reordered[pos]["final_score"] = chunks[orig_i].get("final_score", 0.0) * (
                1.0 + (1 - lambda_param) * 0.2
            )

    # Копируем обратно в исходный список (in-place)
    chunks[:] = reordered

    return chunks
