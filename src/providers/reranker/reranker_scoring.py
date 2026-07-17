"""Scoring helpers для MultiProviderReranker.

Выделены из multi_provider.py для уменьшения god-object.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Регулярка для извлечения JSON-массива scores из ответа
_SCORES_JSON_RE = re.compile(r'\{\s*"scores"\s*:\s*\[.*?\]\s*\}', re.DOTALL)
# Извлечение отдельных объектов {"index": N, "score": F}
_SCORE_ITEM_RE = re.compile(
    r'\{\s*"index"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*\}'
)


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Вычисляет cosine similarity между двумя векторами."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def validate_scores(scores: List[Any]) -> List[Dict[str, Any]]:
    """Валидирует и нормализует список скоров."""
    validated = []
    for item in scores:
        if isinstance(item, dict):
            idx = item.get("index")
            score = item.get("score")
            if isinstance(idx, (int, float)) and isinstance(score, (int, float)):
                validated.append(
                    {
                        "index": int(idx),
                        "score": max(0.0, min(1.0, float(score))),
                    }
                )
    return validated


def parse_scores_json(raw: str) -> List[Dict[str, Any]]:
    """Парсит JSON со скорами из ответа LLM.

    Поддерживает:
    1. Чистый JSON: {"scores": [{"index": 0, "score": 0.95}, ...]}
    2. JSON в markdown-блоке: ```json\n{...}\n```
    3. JSON с окружающим текстом (поиск через regex)

    Returns:
        Список dict'ов [{"index": int, "score": float}, ...]
    """
    if not raw:
        return []

    # Попытка 1: прямой JSON-парсинг
    try:
        data = json.loads(raw)
        scores = data.get("scores", [])
        if isinstance(scores, list) and scores:
            return validate_scores(scores)
    except (json.JSONDecodeError, TypeError):
        pass

    # Попытка 2: извлечение из markdown-блока
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if md_match:
        try:
            data = json.loads(md_match.group(1))
            scores = data.get("scores", [])
            if isinstance(scores, list) and scores:
                return validate_scores(scores)
        except (json.JSONDecodeError, TypeError):
            pass

    # Попытка 3: поиск JSON-объекта через regex
    json_match = _SCORES_JSON_RE.search(raw)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            scores = data.get("scores", [])
            if isinstance(scores, list) and scores:
                return validate_scores(scores)
        except (json.JSONDecodeError, TypeError):
            pass

    # Попытка 4: извлечение отдельных объектов score
    items = _SCORE_ITEM_RE.findall(raw)
    if items:
        return [{"index": int(idx), "score": float(score)} for idx, score in items]

    logger.warning(
        f"Не удалось извлечь scores из ответа реранкера: {raw[:200]}..."
    )
    return []


def apply_scores(
    chunks: List[Dict[str, Any]],
    scores: List[Dict[str, Any]],
    top_n: int,
) -> List[Dict[str, Any]]:
    """Применяет скоры реранкера к чанкам и сортирует."""
    score_map = {s["index"]: s["score"] for s in scores}
    for i, chunk in enumerate(chunks):
        chunk["reranker_score"] = score_map.get(i, 0.0)

    sorted_chunks = sorted(
        chunks,
        key=lambda c: c.get("reranker_score", 0.0),
        reverse=True,
    )

    return sorted_chunks[:top_n]


__all__ = [
    "cosine_similarity",
    "validate_scores",
    "parse_scores_json",
    "apply_scores",
]
