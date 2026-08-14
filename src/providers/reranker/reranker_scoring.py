"""Scoring helpers для MultiProviderReranker.

Выделены из multi_provider.py для уменьшения god-object.
"""
from __future__ import annotations

import json
import logging
import math
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
    """Валидирует и нормализует список скоров.

    Контракт (ground truth для мутационных тестов, evalmut-инвариант):
    - index: неотрицательное ЦЕЛОЕ. bool отбрасывается (bool — подкласс int);
      float принимается только при целочисленном значении — иначе int()
      молча переставил бы скор (напр. 2.7 -> 2); негативный индекс не
      ссылается ни на один чанк.
    - score: конечное число. NaN/Inf отбрасываются — это НЕ «больше 1»,
      а отсутствие оценки: min/max-clamp молча превращал NaN в 1.0
      (максимальный скор неоценённому чанку). Вне [0,1] — clamp
      (by design: логиты реранкера нормализуются).
    Элементы, не прошедшие контракт, отбрасываются (fail-safe: потерянный
    скор лучше переставленного).
    """
    validated = []
    for item in scores:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        score = item.get("score")
        # bool — подкласс int: True не является валидным индексом/скором
        if isinstance(idx, bool) or isinstance(score, bool):
            continue
        if not isinstance(idx, (int, float)) or not isinstance(score, (int, float)):
            continue
        if isinstance(idx, float) and not idx.is_integer():
            continue  # 2.7 -> int() молча переставил бы скор на соседний чанк
        index = int(idx)
        if index < 0:
            continue
        if not math.isfinite(score):
            continue  # NaN/Inf проходили isinstance и становились 1.0/0.0
        validated.append({"index": index, "score": max(0.0, min(1.0, float(score)))})
    return validated


def _finalize_scores(
    parsed: List[Dict[str, Any]],
    raw: str,
    *,
    single_decline: bool,
) -> List[Dict[str, Any]]:
    """Общий выходной фильтр путей парсера: decline при недостоверном извлечении.

    Дубликаты индексов — сигнал «пример формата + реальные скоры» (пример в
    промпте всегда {"index": 0, ...} и совпадёт с реальным 0), а также битого
    ответа LLM — decline во всех путях. Единственный объект — decline ТОЛЬКО
    на regex-пути без обёртки (single_decline=True), где объект мог быть
    примером формата из объяснения; внутри полной обёртки {"scores": [...]}
    одиночный объект легитимен (реальный ответ для одного чанка).
    Возвращаем [] (fail-safe: не сортировать вообще, чем по мусору).
    """
    if not parsed:
        return []
    indices = [s["index"] for s in parsed]
    if len(indices) != len(set(indices)):
        logger.warning(
            f"⚠️ Дублирующиеся индексы скоров (вероятный пример формата "
            f"в ответе), decline: {raw[:200]}..."
        )
        return []
    if single_decline and len(parsed) == 1:
        logger.warning(
            f"⚠️ Единичный объект score без обёртки scores — вероятный "
            f"пример формата, decline: {raw[:200]}..."
        )
        return []
    return parsed


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
            return _finalize_scores(validate_scores(scores), raw, single_decline=False)
    except (json.JSONDecodeError, TypeError):
        pass

    # Попытка 2: извлечение из markdown-блока
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if md_match:
        try:
            data = json.loads(md_match.group(1))
            scores = data.get("scores", [])
            if isinstance(scores, list) and scores:
                return _finalize_scores(validate_scores(scores), raw, single_decline=False)
        except (json.JSONDecodeError, TypeError):
            pass

    # Попытка 3: поиск JSON-объекта через regex
    json_match = _SCORES_JSON_RE.search(raw)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            scores = data.get("scores", [])
            if isinstance(scores, list) and scores:
                return _finalize_scores(validate_scores(scores), raw, single_decline=False)
        except (json.JSONDecodeError, TypeError):
            pass

    # Попытка 4: извлечение отдельных объектов score (fallback: контракт
    # промпта требует полный {"scores": [...]}, но отдельные LLM отвечают
    # голыми объектами). Тот же контракт, что в путях 1-3 (clamp+фильтры).
    items = _SCORE_ITEM_RE.findall(raw)
    if items:
        return _finalize_scores(
            validate_scores(
                [{"index": int(idx), "score": float(score)} for idx, score in items]
            ),
            raw,
            single_decline=True,
        )

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
    n = len(chunks)
    # Диагностика «осиротевших» индексов (>= n): парсер не знает число чанков,
    # поэтому скор, не ссылающийся ни на один чанк, молча терялся. Не влияет
    # на сортировку остальных — но обязан быть видимым в логе (evalmut:
    # coverage gap, а не тихая потеря).
    orphaned = [s["index"] for s in scores if s.get("index", 0) >= n]
    if orphaned:
        logger.warning(
            f"⚠️ Скоры с индексами вне диапазона чанков [0,{n}): {orphaned} — "
            f"вероятно, LLM вернул индексы несуществующих чанков."
        )
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
