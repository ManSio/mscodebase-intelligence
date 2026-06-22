import logging
import re
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class Searcher:
    """Выполняет гибридный поиск по индексированной кодовой базе."""

    def __init__(self, indexer, embedder):
        self.indexer = indexer
        self.embedder = embedder

        self._bm25 = None
        self._bm25_ids: List[str] = []
        self._bm25_lock = threading.Lock()

        # Регулярка для токенизации кода (разбивает по всем не-буквам/цифрам)
        self._tokenizer_re = re.compile(r"\W+")

    def reindex(self):
        """Сбрасывает кэш BM25. Вызывается при изменении индекса."""
        with self._bm25_lock:
            self._bm25 = None
            self._bm25_ids = []
            logger.debug("🔄 Кэш BM25 сброшен")

        # Рекомендуется вызывать build_bm25_index() асинхронно после реиндексации,
        # чтобы избежать задержек при первом поиске.

    def build_bm25_index(self):
        """Принудительно строит BM25 индекс. Лучше запускать в фоне."""
        with self._bm25_lock:
            if self._bm25 is not None:
                return  # Уже построен

            try:
                from rank_bm25 import BM25Okapi

                logger.info("⏳ Построение BM25 индекса...")
                all_docs = self.indexer.collection.get(include=["documents", "ids"])

                if not all_docs["documents"]:
                    return

                self._bm25_ids = all_docs["ids"]

                # Токенизируем, но НЕ сохраняем сами документы в память экземпляра класса
                corpus = [
                    [t for t in self._tokenizer_re.split(doc.lower()) if t]
                    for doc in all_docs["documents"]
                ]

                self._bm25 = BM25Okapi(corpus)
                logger.info(
                    f"✅ BM25 индекс построен: {len(self._bm25_ids)} документов"
                )

            except Exception as e:
                logger.error(f"❌ Ошибка построения BM25: {e}", exc_info=True)

    def search(self, query: str, top_k: int = 5) -> str:
        """Ищет релевантные фрагменты кода. Возвращает отформатированный результат."""
        if not query.strip():
            return "Пустой запрос."

        try:
            # 1. Векторный поиск
            query_embedding = self.embedder.embed(query, is_query=True)
            vector_results = self.indexer.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k * 2,
                include=["documents", "metadatas", "distances"],
            )

            # 2. Keyword поиск (BM25)
            keyword_ids = self._bm25_search(query, top_k * 2)

            # 3. Слияние через RRF
            merged_ids = self._rrf_merge(vector_results, keyword_ids, top_k)

            # 4. Обогащение информацией о символах
            symbol_info = None
            if hasattr(self.indexer, "symbol_index"):
                try:
                    symbol_info = self.indexer.symbol_index.search_symbols(query)
                except Exception:
                    pass

            # 5. Форматирование
            return self._format_results(merged_ids, symbol_info)

        except Exception as e:
            logger.error(f"Ошибка поиска: {e}", exc_info=True)
            return f"❌ Ошибка поиска: {e}"

    def _bm25_search(self, query: str, limit: int) -> List[str]:
        """Keyword поиск через BM25."""
        # Ленивая инициализация: если индекс сброшен, строим его
        if self._bm25 is None:
            self.build_bm25_index()

        with self._bm25_lock:
            bm25 = self._bm25
            ids = self._bm25_ids

        if not bm25:
            return []

        try:
            # Используем тот же токенизатор для запроса
            tokenized_query = [t for t in self._tokenizer_re.split(query.lower()) if t]
            scores = bm25.get_scores(tokenized_query)

            # Топ-K с ненулевым score (используем numpy-like подход или встроенный heapq)
            # Встроенный метод top_n работает быстрее на больших массивах, чем argsort
            import numpy as np

            top_indices = np.argsort(scores)[-limit:][::-1]
            return [ids[i] for i in top_indices if scores[i] > 0]

        except Exception as e:
            logger.warning(f"BM25 поиск не удался: {e}")
            return []

    def _rrf_merge(
        self, vector_results: Dict, keyword_ids: List[str], top_k: int
    ) -> List[str]:
        """Слияние результатов через Reciprocal Rank Fusion."""
        scores: Dict[str, float] = {}

        # Формула RRF: score = 1 / (k + rank)
        # где k обычно 60

        # Векторные результаты
        if vector_results.get("ids") and vector_results["ids"][0]:
            for rank, doc_id in enumerate(vector_results["ids"][0], 1):
                scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (60 + rank)

        # Keyword результаты
        for rank, doc_id in enumerate(keyword_ids, 1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (60 + rank)

        # Сортируем по итоговому score
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        return sorted_ids[:top_k]

    def _format_results(
        self, doc_ids: List[str], symbol_info: Optional[List[Dict]] = None
    ) -> str:
        """Форматирует результаты поиска в читаемый текст."""
        if not doc_ids:
            return "Ничего не найдено."

        try:
            result = self.indexer.collection.get(
                ids=doc_ids, include=["documents", "metadatas"]
            )
        except Exception as e:
            logger.error(f"Ошибка получения результатов: {e}")
            return "❌ Ошибка форматирования результатов."

        if not result.get("documents"):
            return "Ничего не найдено."

        # Строим мапу символ -> информация для быстрого поиска
        symbol_map = {}
        if symbol_info:
            for s in symbol_info:
                name = s.get("symbol")
                if name:
                    symbol_map[name] = s

        lines = []
        for i, (doc, meta) in enumerate(
            zip(result["documents"], result["metadatas"]), 1
        ):
            file_path = meta.get("file", "?")
            start = meta.get("start_line", 0)
            end = meta.get("end_line", 0)
            chunk_type = meta.get("type", "код")

            lines.append(f"{i}. 📄 {file_path}:{start}-{end} ({chunk_type})")

            # Компактный блок кода (первая строка или до 200 символов)
            first_newline = doc.find("\n")
            if first_newline != -1 and first_newline <= 200:
                compact = doc[:first_newline]
            else:
                compact = doc[:200]
            lines.append("```")
            lines.append(compact)
            if len(doc) > len(compact):
                lines.append("...")
            lines.append("```")

            # Информация об использовании символа
            sym_name = meta.get("symbol_name", "")
            if sym_name and sym_name in symbol_map:
                ctx = symbol_map[sym_name]
                used_count = ctx.get("used_in_count", 0)
                lines.append(f"🔗 Используется в {used_count} файлах")

            lines.append("")

        return "\n".join(lines)
