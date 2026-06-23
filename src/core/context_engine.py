"""
MSCodebase Intelligence — Контекстный движок сборки контекста под токены
"""

import logging
from typing import List

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 3000


def get_context(query: str, searcher) -> str:
    if not query.strip():
        return "Запрос пуст."

    try:
        query_vector = searcher.embedder.embed(query)
        chunks = searcher.vector_search(query_vector, limit=8)

        if not chunks:
            return "Релевантный контекст не найден."

        lines = []
        total_chars = 0

        for chunk in chunks:
            # Проверяем, не вернулась ли ошибка
            if "error" in chunk:
                return f"❌ Ошибка поиска: {chunk['error']}"
            file_path = chunk["metadata"]["file"]
            doc = chunk["text"]
            chunk_idx = chunk["metadata"]["chunk_index"]

            block = f"📄 Файл: {file_path} (Фрагмент #{chunk_idx})\n```\n{doc}\n```\n"

            if total_chars + len(block) > MAX_CONTEXT_CHARS - 100:
                break

            lines.append(block)
            total_chars += len(block)

        return (
            f"📊 Сформированный контекст проекта ({len(lines)} фрагментов):\n\n"
            + "\n".join(lines)
        )
    except Exception as e:
        logger.error(f"Ошибка генерации контекста в ContextEngine: {e}")
        return f"❌ Ошибка формирования контекста: {e}"
