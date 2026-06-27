"""
MSCodebase Intelligence — Контекстный движок сборки контекста под токены
"""

import logging

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 8000


def get_context(query: str, searcher) -> str:
    if not query.strip():
        return "Запрос пуст."

    try:
        # Используем гибридный поиск с RRF
        chunks = searcher.hybrid_search(query, limit=10)

        if not chunks:
            return "Релевантный контекст не найден."

        lines = []
        total_chars = 0

        for chunk in chunks:
            file_path = chunk["metadata"]["file"]
            doc = chunk["text"]
            chunk_idx = chunk["metadata"]["chunk_index"]
            final_score = chunk.get("final_score", 0.0)

            # Сжимаем: если чанк > 600 символов, обрезаем с маркером
            if len(doc) > 600:
                doc = doc[:600] + "\n..."

            block = f"📄 {file_path}:{chunk_idx} (score={final_score:.4f})\n```\n{doc}\n```\n"

            if total_chars + len(block) > MAX_CONTEXT_CHARS - 100:
                break

            lines.append(block)
            total_chars += len(block)

        return (
            f"📊 Сформированный контекст ({len(lines)} фрагментов, RRF fusion):\n\n"
            + "\n".join(lines)
        )
    except Exception as e:
        logger.error(f"Ошибка генерации контекста в ContextEngine: {e}")
        return f"❌ Ошибка формирования контекста: {e}"
