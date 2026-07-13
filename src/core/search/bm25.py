"""BM25 sparse retrieval mixin extracted from engine.py.

Contains BM25Mixin class with methods for building, searching, and
incrementally updating the BM25 index.  Designed to be mixed into
Searcher via class inheritance.
"""

import asyncio
import logging
import math
import threading
from typing import Any, Dict, List, Optional

from src.core.search.utils import _tokenize

logger = logging.getLogger(__name__)


class BM25Mixin:
    """Mixin that adds BM25 sparse-retrieval capabilities.

    Expects the host class to provide the following attributes
    (typically set in ``__init__``):

    * ``self._bm25`` — Optional[Dict[str, Dict[str, float]]]
    * ``self._bm25_ids`` — List[str]
    * ``self._bm25_lock`` — threading.Lock
    * ``self._bm25_df`` — Any (cached pandas DataFrame)
    * ``self._tokenizer_re`` — re.Pattern
    * ``self.indexer`` — Indexer instance (needs ``.table``)
    """

    # ── Public API ────────────────────────────────────────────

    def reindex(self):
        """Сбрасывает BM25-индекс, forcing полную перестройку при следующем поиске."""
        with self._bm25_lock:
            self._bm25 = None
            self._bm25_ids = []
            self._bm25_df = None
        logger.debug("Индекс BM25 сброшен для реиндексации")

    def _reset_bm25(self) -> None:
        """Quick BM25 invalidation for meta-patching.

        Called by Indexer.apply_file_move after a file rename
        to force BM25 rebuild on next search.
        """
        with self._bm25_lock:
            self._bm25 = None
            self._bm25_ids = []
            self._bm25_df = None
        logger.debug("BM25 сброшен после meta-patch")

    # ── Index building ────────────────────────────────────────

    def _build_bm25_index(self) -> None:
        """Ленивая инициализация BM25 индекса из текущей таблицы LanceDB.

        Потокобезопасна: использует _bm25_lock для предотвращения конкурентного
        построения индекса из нескольких потоков.
        Если таблица повреждена или пуста — BM25 остаётся пустым (degraded mode),
        поиск продолжит работу только через векторный поиск.
        """
        if self._bm25 is not None:
            return

        with self._bm25_lock:
            # Double-check после захвата блокировки
            if self._bm25 is not None:
                return
            if self.indexer.table is None:
                self._bm25 = {}
                return

            # Проверяем, что таблица доступна (count_rows — лёгкая операция)
            try:
                table_ok = self.indexer.table.count_rows()
                if table_ok == 0:
                    self._bm25 = {}
                    return
            except Exception:
                # Таблица недоступна — работаем в degraded mode
                logger.warning(
                    "📊 BM25: таблица недоступна, работаем только через векторный поиск"
                )
                self._bm25 = {}
                return

            try:
                df = self.indexer.table.to_pandas()
                if df is None or df.empty:
                    self._bm25 = {}
                    return

                # Кэшируем DataFrame для _bm25_search (избегаем двойной загрузки)
                self._bm25_df = df

                # Считаем TF для каждого термина в каждом документе
                doc_count = len(df)
                term_doc_freq: Dict[str, int] = {}
                term_doc_scores: Dict[str, Dict[str, float]] = {}

                for _, row in df.iterrows():
                    doc_id = f"{row['file_path']}:{row['chunk_index']}"
                    text = str(row.get("text", ""))
                    tokens = _tokenize(text, self._tokenizer_re)

                    # TF (частота термина в документе)
                    term_tf: Dict[str, float] = {}
                    for token in tokens:
                        term_tf[token] = term_tf.get(token, 0) + 1

                    # Сохраняем TF для документа
                    self._bm25_ids.append(doc_id)
                    term_doc_scores[doc_id] = term_tf

                    # DF (число документов, содержащих термин)
                    for token in term_tf:
                        term_doc_freq[token] = term_doc_freq.get(token, 0) + 1

                # Вычисляем IDF: log((N - df + 0.5) / (df + 0.5))
                self._bm25 = {}
                for doc_id, tf_dict in term_doc_scores.items():
                    self._bm25[doc_id] = {}
                    for term, tf in tf_dict.items():
                        df = term_doc_freq.get(term, 0)
                        idf = math.log((doc_count - df + 0.5) / (df + 0.5) + 1)
                        self._bm25[doc_id][term] = tf * idf

                logger.debug(f"📊 BM25 индекс построен: {len(self._bm25)} документов")
            except Exception as e:
                logger.error(f"Ошибка построения BM25 индекса: {e}")
                self._bm25 = {}
                self._bm25_ids = []
                self._bm25_df = None

    # ── Incremental update ────────────────────────────────────

    def incremental_update_bm25(self, new_chunks: List[dict]) -> None:
        """Инкрементально обновляет BM25 индекс при добавлении новых чанков.

        Вместо полной перестройки индекса (что дорого при большом объёме данных)
        добавляет только новые документы в существующий индекс.

        Args:
            new_chunks: Список новых чанков с ключами 'file_path', 'chunk_index', 'text'.
                Каждый элемент должен содержать как минимум:
                - file_path: относительный путь к файлу
                - chunk_index: индекс чанка
                - text: текстовое содержимое чанка
        """
        if not new_chunks:
            return

        with self._bm25_lock:
            # Если индекс ещё не построен — полная перестройка
            if self._bm25 is None:
                self._build_bm25_index()
                return

            try:
                # Получаем текущее количество документов для IDF
                doc_count = len(self._bm25)

                # Загружаем DF из существующего индекса
                term_doc_freq: Dict[str, int] = {}
                for doc_id, tf_dict in self._bm25.items():
                    for term in tf_dict:
                        term_doc_freq[term] = term_doc_freq.get(term, 0) + 1

                # Добавляем новые чанки
                for chunk in new_chunks:
                    doc_id = f"{chunk['file_path']}:{chunk['chunk_index']}"
                    if doc_id in self._bm25:
                        continue  # Уже есть — пропускаем

                    text = str(chunk.get("text", ""))
                    tokens = _tokenize(text, self._tokenizer_re)

                    # TF для нового документа
                    term_tf: Dict[str, float] = {}
                    for token in tokens:
                        term_tf[token] = term_tf.get(token, 0) + 1

                    self._bm25_ids.append(doc_id)
                    self._bm25[doc_id] = term_tf

                    # Обновляем DF
                    for token in term_tf:
                        term_doc_freq[token] = term_doc_freq.get(token, 0) + 1

                # Пересчитываем IDF для всех документов (включая новые)
                total_docs = doc_count + len(new_chunks)
                for doc_id, tf_dict in self._bm25.items():
                    for term, tf in tf_dict.items():
                        df = term_doc_freq.get(term, 0)
                        idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1)
                        self._bm25[doc_id][term] = tf * idf

                logger.debug(
                    f"📊 BM25 индекс обновлён инкрементально: "
                    f"+{len(new_chunks)} документов, всего {len(self._bm25)}"
                )
            except Exception as e:
                logger.error(f"Ошибка инкрементального обновления BM25: {e}")
                # При ошибке сбрасываем индекс для полной перестройки
                self._bm25 = None
                self._bm25_ids = []
                self._bm25_df = None

    # ── Search ────────────────────────────────────────────────

    def _bm25_search(self, query: str, limit: int = 5) -> List[dict]:
        """Полнотекстовый поиск BM25 по текущей базе."""
        self._build_bm25_index()
        if not self._bm25:
            return []

        query_tokens = _tokenize(query, self._tokenizer_re)
        scores: Dict[str, float] = {}

        for doc_id in self._bm25_ids:
            scores[doc_id] = 0.0
            for token in query_tokens:
                scores[doc_id] += self._bm25[doc_id].get(token, 0.0)

        # Сортируем по убыванию скора
        top_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:limit]

        # Формируем результаты (используем кэшированный DataFrame)
        results = []
        try:
            df = self._bm25_df
            if df is None or df.empty:
                return results
            for doc_id in top_ids:
                if scores[doc_id] <= 0:
                    continue
                file_path, chunk_idx = doc_id.rsplit(":", 1)
                match = df[
                    (df["file_path"] == file_path)
                    & (df["chunk_index"] == int(chunk_idx))
                ]
                if not match.empty:
                    row = match.iloc[0]
                    results.append(
                        {
                            "text": row["text"],
                            "text_full": row.get("text_full", row["text"]),
                            "metadata": {
                                "file": row["file_path"],
                                "chunk_index": row["chunk_index"],
                                "indexed_at": row.get("indexed_at", ""),
                                "layer": row.get("layer", ""),
                            },
                        }
                    )
        except Exception as e:
            logger.error(f"Ошибка выполнения BM25 поиска: {e}")

        return results

    # ── Async wrapper ─────────────────────────────────────────

    async def _bm25_search_async(self, query: str, limit: int = 5) -> List[dict]:
        """Асинхронная обёртка для BM25 поиска (не блокирует event loop)."""
        return await asyncio.to_thread(self._bm25_search, query, limit)
