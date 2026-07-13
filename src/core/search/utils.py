"""Module-level utility functions extracted from engine.py.

Contains pure functions (no `self`-needed) for query expansion,
tokenization, datetime parsing, filtering, and symbol extraction.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Query synonyms ───────────────────────────────────────────
_QUERY_SYNONYMS = {
    "auth": ["authentication", "login", "authorize"],
    "login": ["auth", "signin", "authenticate"],
    "config": ["configuration", "settings", "options"],
    "error": ["exception", "failure", "bug"],
    "create": ["add", "insert", "new"],
    "delete": ["remove", "destroy", "clear"],
    "update": ["edit", "modify", "change"],
    "get": ["fetch", "retrieve", "read"],
}


def _expand_query(query: str, max_expansions: int = 3) -> List[str]:
    """Расширяет запрос синонимами для улучшения полноты поиска."""
    variants = [query]
    words = query.lower().split()
    for word in words:
        synonyms = _QUERY_SYNONYMS.get(word, [])
        for syn in synonyms[: max_expansions - 1]:
            variant = query.replace(word, syn, 1)
            if variant not in variants:
                variants.append(variant)
                if len(variants) >= max_expansions:
                    return variants
    return variants


def _tokenize(text: str, tokenizer_re: re.Pattern) -> List[str]:
    """Простейшее токенизирование для BM25."""
    return tokenizer_re.split(text.lower()) if text else []


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    """Парсит ISO datetime string в datetime (timezone-aware).

    Поддерживает форматы:
    - "2026-06-30T14:30:00"
    - "2026-06-30T14:30:00+03:00"
    - "2026-06-30"
    """
    if not value:
        return None
    try:
        # Python 3.11+ поддерживает большинство ISO форматов
        dt = datetime.fromisoformat(value)
        # Если нет timezone — считаем UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        logger.warning(f"Не удалось распарсить datetime: {value!r}")
        return None


def _filter_by_time(
    results: List[dict],
    since: Optional[str] = None,
    before: Optional[str] = None,
) -> List[dict]:
    """Фильтрует результаты по indexed_at.

    Args:
        results: Список результатов поиска (каждый содержит metadata.indexed_at)
        since: ISO datetime — только чанки проиндексированные после этого времени
        before: ISO datetime — только чанки проиндексированные до этого времени

    Returns:
        Отфильтрованный список результатов
    """
    if not since and not before:
        return results

    since_dt = _parse_iso_datetime(since)
    before_dt = _parse_iso_datetime(before)

    filtered = []
    for r in results:
        indexed_at_str = r.get("metadata", {}).get("indexed_at", "")
        if not indexed_at_str:
            # Чанки без indexed_at пропускаем при любой фильтрации
            continue

        indexed_dt = _parse_iso_datetime(indexed_at_str)
        if indexed_dt is None:
            continue

        if since_dt and indexed_dt < since_dt:
            continue
        if before_dt and indexed_dt > before_dt:
            continue

        filtered.append(r)

    return filtered


def _extract_key_terms(results: List[dict], max_terms: int = 5) -> List[str]:
    """Извлекает ключевые термины из результатов поиска для уточнения запроса.

    Анализирует текст топ-результатов, выделяя редкие, но значимые термины,
    которые могут улучшить поиск на следующей итерации.

    Args:
        results: Результаты поиска
        max_terms: Максимальное число терминов для извлечения

    Returns:
        Список ключевых терминов
    """
    if not results:
        return []

    # Собираем частотность терминов в результатах
    term_freq: Dict[str, int] = {}
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then",
        "once", "here", "there", "when", "where", "why", "how", "all", "each",
        "every", "both", "few", "more", "most", "other", "some", "such", "no",
        "nor", "not", "only", "own", "same", "so", "than", "too", "very",
        "just", "because", "but", "and", "or", "if", "while", "return", "def",
        "class", "import", "from", "self", "none", "true", "false", "pass",
        "that", "this", "it", "its", "what", "which", "who", "whom",
    }

    for r in results[:5]:
        text = r.get("text", "").lower()
        # Извлекаем идентификаторы (CamelCase, snake_case)
        tokens = re.findall(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", text)
        for token in tokens:
            if len(token) >= 4 and token not in stop_words:
                term_freq[token] = term_freq.get(token, 0) + 1

    # Сортируем по частотности, берём топ-N самых редких (но встречающихся)
    sorted_terms = sorted(term_freq.items(), key=lambda x: x[1], reverse=True)
    # Предпочитаем термины, которые встречаются в 2+ документах (значимые)
    significant = [t for t, f in sorted_terms if f >= 2][:max_terms]
    # Если нет значимых, берём топ-N по частотности
    if not significant:
        significant = [t for t, _ in sorted_terms[:max_terms]]

    return significant


def _extract_symbol_name(text: str) -> Optional[str]:
    """Извлекает имя символа из текста чанка."""
    # Паттерны для извлечения имен символов
    patterns = [
        r"def\s+(\w+)",          # def function_name
        r"class\s+(\w+)",        # class ClassName
        r"(\w+)\s*=\s*function", # variable = function
        r"function\s+(\w+)",     # function name
        r"const\s+(\w+)\s*=",    # const variable =
        r"let\s+(\w+)\s*=",      # let variable =
        r"var\s+(\w+)\s*=",      # var variable =
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)

    return None
