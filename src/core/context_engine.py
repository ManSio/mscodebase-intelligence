"""
Контекстный движок — умный сбор контекста для AI агента.

Как Cursor @codebase:
1. Автоматически определяет, что искать по вопросу
2. Делает несколько параллельных поисков (keyword, vector, symbol)
3. Собирает компактный контекст с контролем токенов
4. Возвращает ТОЛЬКО самое важное, ничего лишнего

Usage:
    from src.core.context_engine import get_context
    result = get_context("Найди функцию обработки ошибок")
"""

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Сколько символов (не токенов) максимум на ответ
# ~4 символа = 1 токен. Даём ~750 токенов = 3000 символов
MAX_CONTEXT_CHARS = 3000

# Сколько максимум чанков возвращаем
MAX_CHUNKS = 8

# Минимум символов в чанке чтобы он считался полезным
MIN_CHUNK_CHARS = 40


def get_context(query: str, searcher, top_k: int = 5) -> str:
    """
    Главная функция: умный сбор контекста под вопрос AI.

    Делает несколько проходов поиска, собирает результаты,
    укладывается в лимит токенов.
    """
    if not query.strip():
        return ""

    try:
        # ШАГ 1: Разбираем вопрос на ключевые слова и сущности
        keywords = _extract_keywords(query)
        symbols_from_query = _extract_potential_symbols(query)

        logger.debug(f"Ключевые слова: {keywords}")
        logger.debug(f"Потенциальные символы: {symbols_from_query}")

        # ШАГ 2: Параллельные поиски разными методами
        results = {}  # chunk_id -> score

        # 2a. Семантический поиск (векторный) — главный
        semantic_hits = _semantic_search(query, searcher, top_k=top_k * 2)
        for cid, score in semantic_hits:
            results[cid] = results.get(cid, 0) + score * 2.0  # векторный весомее

        # 2b. BM25 (keyword) поиск
        keyword_hits = _keyword_search(query, keywords, searcher, top_k=top_k * 2)
        for cid, score in keyword_hits:
            results[cid] = results.get(cid, 0) + score * 1.5

        # 2c. Поиск по именам символов (если вопрос про функцию/класс)
        if symbols_from_query:
            for sym in symbols_from_query:
                symbol_hits = _symbol_search(sym, searcher, top_k=top_k)
                for cid, score in symbol_hits:
                    results[cid] = (
                        results.get(cid, 0) + score * 2.5
                    )  # символы важнее всего

        # ШАГ 3: Сортируем по скору и отбираем топ
        ranked = sorted(results.items(), key=lambda x: -x[1])

        # ШАГ 4: Собираем контекст с контролем токенов и разнообразием
        context = _build_compact_context(ranked, searcher, top_k)

        return context

    except Exception as e:
        logger.error(f"Ошибка get_context: {e}", exc_info=True)
        # Fallback: обычный поиск
        try:
            return searcher.search(query, top_k)
        except Exception:
            return f"⚠️ Ошибка: {e}"


# ─── ШАГ 1: Разбор вопроса ───


def _extract_keywords(query: str) -> List[str]:
    """Извлекает значимые ключевые слова из вопроса.

    Фильтрует стоп-слова, оставляет только осмысленные термины.
    """
    # Стоп-слова (русские и английские)
    stop_words = {
        "найди",
        "найти",
        "покажи",
        "где",
        "как",
        "что",
        "кто",
        "этот",
        "эта",
        "это",
        "эти",
        "который",
        "которая",
        "которое",
        "find",
        "show",
        "where",
        "what",
        "which",
        "how",
        "who",
        "the",
        "a",
        "an",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
        "and",
        "or",
        "but",
        "if",
        "because",
        "as",
        "until",
        "while",
        "about",
        "between",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "from",
        "up",
        "down",
        "out",
        "off",
        "over",
        "then",
        "once",
        "here",
        "there",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "because",
        "also",
    }

    # Разбиваем на слова
    words = re.findall(r"[а-яА-Яa-zA-Z_][а-яА-Яa-zA-Z0-9_]*", query.lower())

    # Фильтруем стоп-слова и короткие слова
    keywords = [w for w in words if w not in stop_words and len(w) > 1]

    return keywords


def _extract_potential_symbols(query: str) -> List[str]:
    """Извлекает потенциальные имена символов из вопроса.

    Срабатывает, если в вопросе есть CamelCase, snake_case,
    или конкретные имена после слов 'функция', 'класс', 'метод'.
    """
    symbols = []

    # CamelCase — вероятно имя класса или компонента
    camel_case = re.findall(r"\b[A-Z][a-z]+[A-Z][a-zA-Z0-9]*\b", query)
    symbols.extend(camel_case)

    # snake_case — вероятно имя функции или переменной
    snake_case = re.findall(r"\b[a-z]+_[a-z_0-9]+\b", query.lower())
    symbols.extend(snake_case)

    # Слова после маркеров "функция", "класс", "метод"
    marker_pattern = re.compile(
        r"(?:функци[яюи]|класс[а]?|метод[а]?|function|class|method)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        re.IGNORECASE,
    )
    for m in marker_pattern.finditer(query):
        symbols.append(m.group(1))

    return list(set(symbols))


# ─── ШАГ 2: Множественные поиски ───


def _semantic_search(query: str, searcher, top_k: int) -> List[Tuple[str, float]]:
    """Векторный поиск по смыслу запроса."""
    try:
        query_embedding = searcher.embedder.embed(query)
        if not query_embedding:
            return []

        results = searcher.indexer.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["metadatas", "distances"],
        )

        hits = []
        if results.get("ids") and results["ids"][0]:
            for i, cid in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results.get("distances") else 0
                # Конвертируем distance в score (1.0 - distance)
                score = max(0, 1.0 - distance)
                hits.append((cid, score))
        return hits
    except Exception as e:
        logger.warning(f"Семантический поиск не удался: {e}")
        return []


def _keyword_search(
    query: str, keywords: List[str], searcher, top_k: int
) -> List[Tuple[str, float]]:
    """Keyword поиск через BM25."""
    # Используем оригинальный запрос + извлечённые ключевые слова
    search_terms = query
    if keywords:
        # Если есть ключевые слова, добавляем их с весом
        search_terms = query + " " + " ".join(keywords * 3)

    try:
        keyword_ids = searcher._bm25_search(search_terms, limit=top_k)
        # BM25 возвращает просто id, без скора. Даём константный score.
        return [(cid, 0.5) for cid in keyword_ids]
    except Exception as e:
        logger.warning(f"Keyword поиск не удался: {e}")
        return []


def _symbol_search(symbol_name: str, searcher, top_k: int) -> List[Tuple[str, float]]:
    """Поиск чанков, содержащих определённый символ."""
    try:
        symbol_index = getattr(searcher.indexer, "symbol_index", None)
        if not symbol_index:
            return []

        ctx = symbol_index.get_symbol_context(symbol_name)
        if not ctx:
            return []

        # Ищем чанки, которые содержат этот символ
        # Используем keyword поиск по имени символа
        hits = searcher._bm25_search(symbol_name, limit=top_k)
        return [(cid, 0.8) for cid in hits]
    except Exception as e:
        logger.warning(f"Symbol поиск не удался: {e}")
        return []


# ─── ШАГ 3-4: Сбор контекста ───


def _build_compact_context(
    ranked: List[Tuple[str, float]], searcher, max_chunks: int
) -> str:
    """
    Собирает компактный контекст из лучших результатов.

    Ключевые решения для экономии токенов:
    1. Не дублируем файлы — не больше 2 чанков из одного файла
    2. Берём только сигнатуру (первую строку) + тело до 200 символов
    3. Обрезаем всё до MAX_CONTEXT_CHARS
    4. Сортируем чанки по файлам (чтобы AI было удобнее)
    """
    if not ranked:
        return "Ничего не найдено."

    try:
        # Берём все id
        all_ids = [cid for cid, _ in ranked[: max_chunks * 3]]

        # Получаем метаданные
        result = searcher.indexer.collection.get(
            ids=all_ids, include=["documents", "metadatas"]
        )

        if not result.get("documents"):
            return "Ничего не найдено."

        # Собираем чанки с метаданными и скорами
        id_to_data = {}
        for doc, meta in zip(result["documents"], result["metadatas"]):
            cid = meta.get("id", "")
            if not cid:
                continue
            id_to_data[cid] = (doc, meta)

        # Сортируем по скору и применяем diversity filter
        selected = []
        files_seen = set()

        for cid, score in ranked:
            if len(selected) >= max_chunks:
                break

            if cid not in id_to_data:
                continue

            doc, meta = id_to_data[cid]
            file_path = meta.get("file", "")

            # Пропускаем пустые чанки
            if len(doc.strip()) < MIN_CHUNK_CHARS:
                continue

            # Diversity: максимум 2 чанка из одного файла
            if file_path in files_seen:
                continue  # уже есть чанк из этого файла, пропускаем
            files_seen.add(file_path)

            selected.append((score, file_path, doc, meta))

        if not selected:
            return "Ничего не найдено."

        # Сортируем результаты по файлам для читаемости
        selected.sort(key=lambda x: x[1])

        # Форматируем
        lines = []
        total_chars = 0

        for i, (score, file_path, doc, meta) in enumerate(selected, 1):
            # Сигнатура (первая строка)
            first_newline = doc.find("\n")
            if first_newline != -1 and first_newline < 200:
                signature = doc[:first_newline]
                body = doc[
                    first_newline + 1 : first_newline + 201
                ]  # до 200 символов тела
            elif len(doc) <= 200:
                signature = doc
                body = ""
            else:
                signature = doc[:200]
                body = ""

            start_line = meta.get("start_line", 0)
            end_line = meta.get("end_line", 0)

            # Формируем блок
            block = f"📄 {file_path}:{start_line}-{end_line}\n"
            block += f"```\n{signature}\n"
            if body:
                block += body + "\n"
            if len(doc) > len(signature) + len(body):
                block += "...\n"
            block += "```\n"

            # Проверяем, влезет ли блок в лимит
            if (
                total_chars + len(block) > MAX_CONTEXT_CHARS - 200
            ):  # резерв 200 символов
                break

            lines.append(block)
            total_chars += len(block)

        if not lines:
            return "Ничего не найдено."

        return f"📊 Контекст ({len(lines)} фрагментов):\n\n" + "\n".join(lines).strip()

    except Exception as e:
        logger.error(f"Ошибка сборки контекста: {e}")
        # Fallback на обычный поиск
        try:
            return searcher.search(
                " ".join([cid for cid, _ in ranked[:3]]), len(ranked)
            )
        except Exception:
            return f"❌ Ошибка: {e}"
