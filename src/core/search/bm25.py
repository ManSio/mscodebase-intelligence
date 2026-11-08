"""BM25 sparse retrieval mixin extracted from engine.py.

Contains BM25Mixin class with methods for building, searching, and
incrementally updating the BM25 index.  Designed to be mixed into
Searcher via class inheritance.
"""

import asyncio
import logging
import math
from typing import Dict, List

from src.core.search.utils import _tokenize

__all__ = [
    "BM25Mixin",
]
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
            self._bm25_idf = {}
            self._bm25_doc_len = {}
            self._bm25_avgdl = 0.0
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
            self._bm25_idf = {}
            self._bm25_doc_len = {}
            self._bm25_avgdl = 0.0
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
            # Phase 3: BM25 source is the SQLite chunk store, not LanceDB.
            if getattr(self, "_chunk_store", None) is not None:
                try:
                    if self._chunk_store.count() > 0:
                        self._build_bm25_from_records(self._chunk_store.all_records())
                        return
                except Exception as e:
                    logger.warning(f"BM25: SQLite chunk store unavailable: {e}")
                    self._bm25 = {}
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

    def _build_bm25_from_records(self, records: List[dict]) -> None:
        """Build BM25 from SQLite chunk records (Phase 3, no LanceDB)."""
        if getattr(self, "_code_bm25", False):
            self._build_code_bm25_from_records(records)
            return
        self._bm25_ids = []
        self._bm25_df = None
        self._bm25_rows = {}
        if not records:
            self._bm25 = {}
            return
        doc_count = len(records)
        term_doc_freq: Dict[str, int] = {}
        term_doc_scores: Dict[str, Dict[str, float]] = {}
        for row in records:
            doc_id = f"{row['file_path']}:{row['chunk_index']}"
            self._bm25_rows[doc_id] = row
            tokens = _tokenize(str(row.get("text", "")), self._tokenizer_re)
            term_tf: Dict[str, float] = {}
            for token in tokens:
                term_tf[token] = term_tf.get(token, 0) + 1
            self._bm25_ids.append(doc_id)
            term_doc_scores[doc_id] = term_tf
            for token in term_tf:
                term_doc_freq[token] = term_doc_freq.get(token, 0) + 1
        self._bm25 = {}
        for doc_id, tf_dict in term_doc_scores.items():
            self._bm25[doc_id] = {}
            for term, tf in tf_dict.items():
                df = term_doc_freq.get(term, 0)
                idf = math.log((doc_count - df + 0.5) / (df + 0.5) + 1)
                self._bm25[doc_id][term] = tf * idf
        logger.debug(f"📊 BM25 индекс построен из SQLite: {len(self._bm25)} документов")

    def _build_code_bm25_from_records(self, records: List[dict]) -> None:
        """E32: code-aware BM25 (identifier split, field boosts, k1/b)."""
        from .code_tokenizer import tokenize_code

        self._bm25_ids = []
        self._bm25_df = None
        self._bm25_rows = {}
        self._bm25_idf = {}
        self._bm25_doc_len = {}
        self._bm25_avgdl = 0.0
        if not records:
            self._bm25 = {}
            return

        stop = bool(getattr(self, "_code_bm25_stopwords", True))
        term_doc_freq: Dict[str, int] = {}
        term_tf: Dict[str, Dict[str, int]] = {}
        total_len = 0
        for row in records:
            doc_id = f"{row['file_path']}:{row['chunk_index']}"
            self._bm25_rows[doc_id] = row
            name = tokenize_code(str(row.get("symbol_name", "")), stopwords=stop)
            path = tokenize_code(str(row.get("file_path", "")), stopwords=stop)
            body = tokenize_code(str(row.get("text", "")), stopwords=stop)
            # Field boosts: name x3, path x2, body x1 (ripvec/pi-lens style).
            tokens = name * 3 + path * 2 + body
            tf: Dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            term_tf[doc_id] = tf
            self._bm25_ids.append(doc_id)
            self._bm25_doc_len[doc_id] = len(tokens)
            total_len += len(tokens)
            for tok in tf:
                term_doc_freq[tok] = term_doc_freq.get(tok, 0) + 1

        n = len(records)
        self._bm25_avgdl = (total_len / n) if n else 0.0
        for term, df in term_doc_freq.items():
            self._bm25_idf[term] = math.log(
                1.0 + (n - df + 0.5) / (df + 0.5)
            )
        self._bm25 = term_tf
        logger.debug(
            f"📊 code BM25: {n} docs, avgdl={self._bm25_avgdl:.1f}, "
            f"k1={self._code_bm25_k1}, b={self._code_bm25_b}"
        )

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

        scores: Dict[str, float] = {}
        if getattr(self, "_code_bm25", False):
            from .code_tokenizer import tokenize_code

            query_tokens = tokenize_code(
                query, stopwords=bool(getattr(self, "_code_bm25_stopwords", True))
            )
            k1 = float(getattr(self, "_code_bm25_k1", 1.2))
            b = float(getattr(self, "_code_bm25_b", 0.45))
            avg = float(getattr(self, "_bm25_avgdl", 0.0) or 1.0)
            for doc_id in self._bm25_ids:
                scores[doc_id] = 0.0
                dl = float(getattr(self, "_bm25_doc_len", {}).get(doc_id, 0))
                norm = k1 * (1.0 - b + b * dl / avg)
                for token in query_tokens:
                    tf = self._bm25.get(doc_id, {}).get(token, 0)
                    if not tf:
                        continue
                    idf = getattr(self, "_bm25_idf", {}).get(token, 0.0)
                    scores[doc_id] += idf * (tf * (k1 + 1.0)) / (tf + norm)
        else:
            query_tokens = _tokenize(query, self._tokenizer_re)
            for doc_id in self._bm25_ids:
                scores[doc_id] = 0.0
                for token in query_tokens:
                    scores[doc_id] += self._bm25[doc_id].get(token, 0.0)

        # Сортируем по убыванию скора
        top_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:limit]

        # Формируем результаты (используем кэшированный DataFrame)
        results = []
        try:
            if self._bm25_df is None:
                rows_by_id = getattr(self, "_bm25_rows", None) or {}
                for doc_id in top_ids:
                    if scores[doc_id] <= 0:
                        continue
                    row = rows_by_id.get(doc_id)
                    if not row:
                        continue
                    results.append(
                        {
                            "text": row.get("text", ""),
                            "text_full": row.get("text_full", row.get("text", "")),
                            "metadata": {
                                "file": row.get("file_path", ""),
                                "chunk_index": row.get("chunk_index", 0),
                                "indexed_at": row.get("indexed_at", ""),
                                "layer": row.get("layer", ""),
                            },
                        }
                    )
                return results
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
