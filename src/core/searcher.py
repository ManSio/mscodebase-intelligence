import asyncio
import inspect
import json
import logging
import math
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from src.core.config import (
    CODE_EXTENSIONS,
    DOCS_EXTENSIONS,
    MAX_RERANKER_INPUT,
    get_config,
)
from src.core.reranker import MultiProviderReranker, SearchResultReranker
from src.utils.i18n import _

# Простая функция расширения запроса синонимами (встроена после удаления query_expansion.py)
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


logger = logging.getLogger(__name__)


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


class Searcher:
    """Выполняет гибридный семантический поиск по кодовой базе."""

    # Режимы поиска
    MODE_FAST = "fast"  # ~2300ms: embed + vector only (ONNX CPU)
    MODE_QUALITY = "quality"  # ~5600ms: embed + vector + rerank (ONNX CPU)
    MODE_DEEP = "deep"  # ~2-5s: full analysis + graph

    def __init__(self, indexer, embedder):
        self.indexer = indexer
        self.embedder = embedder
        self._bm25: Optional[Dict[str, Dict[str, float]]] = None
        self._bm25_ids: List[str] = []
        self._bm25_lock = threading.Lock()
        self._bm25_df: Any = None  # кэш DataFrame для _bm25_search
        self._tokenizer_re = re.compile(r"\W+")
        self._reranker = SearchResultReranker(bm25_weight=0.3, dense_weight=0.7)
        # Мульти-провайдерный реранкер (Ollama / LM Studio) — ленивая инициализация
        self._multi_reranker: Optional[MultiProviderReranker] = None
        self._multi_reranker_initialized: bool = False
        self._multi_reranker_lock = asyncio.Lock()
        # Кэш запросов (query -> results)
        self._cache: Dict[str, List[dict]] = {}
        self._cache_max_size = 100

    def reindex(self):
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

    async def close(self) -> None:
        """Освобождает ресурсы реранкера и кэш.

        Безопасно для многократного вызова.
        """
        self._cache.clear()
        if self._multi_reranker is not None:
            try:
                await self._multi_reranker.close()
            except Exception as e:
                logger.debug(f"Close MultiProviderReranker: {e}")
            finally:
                self._multi_reranker = None
                self._multi_reranker_initialized = False
        # Закрываем async LanceDB соединение Indexer-а
        if self.indexer is not None and hasattr(self.indexer, "close_async"):
            try:
                await self.indexer.close_async()
            except Exception as e:
                logger.debug(f"Close async LanceDB Indexer: {e}")

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

        Returns:
            None
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

    def vector_search(
        self,
        query_vector: List[float],
        limit: int = 5,
        filter_expr: str = "",
    ) -> List[dict]:
        """Прямой векторный поиск через таблицу LanceDB.

        Args:
            filter_expr: SQL-выражение для фильтрации (например, "layer = 'core'")
        """
        if self.indexer.table is None:
            return []
        try:
            # Проверяем доступность таблицы лёгким count_rows
            try:
                if self.indexer.table.count_rows() == 0:
                    return []
            except Exception:
                return []

            search_obj = self.indexer.table.search(
                query_vector, vector_column_name="vector"
            )
            if filter_expr:
                search_obj = search_obj.where(filter_expr, prefilter=True)
            df = search_obj.limit(limit).to_pandas()

            results = []
            for _, row in df.iterrows():
                results.append(
                    {
                        "text": row["text"],
                        "text_full": row.get("text_full", row["text"]),
                        "metadata": {
                            "file": row["file_path"],
                            "chunk_index": row["chunk_index"],
                            "indexed_at": row.get("indexed_at", ""),
                            "layer": row.get("layer", ""),
                            "hierarchy_level": row.get("hierarchy_level", ""),
                            "parent_id": row.get("parent_id", ""),
                        },
                    }
                )
            return results
        except Exception as e:
            logger.error(f"Ошибка векторного поиска LanceDB: {e}")
            return [{"error": str(e)}]

    async def _bm25_search_async(self, query: str, limit: int = 5) -> List[dict]:
        """Асинхронная обёртка для BM25 поиска (не блокирует event loop)."""
        return await asyncio.to_thread(self._bm25_search, query, limit)

    async def _vector_search_async(
        self,
        query_vector: List[float],
        limit: int = 5,
        filter_expr: str = "",
    ) -> List[dict]:
        """Асинхронный векторный поиск через Indexer.search_async.

        Использует нативный async LanceDB API (без asyncio.to_thread).
        """
        if query_vector is None:
            return []
        try:
            return await self.indexer.search_async(
                query_vector, limit=limit, filter_expr=filter_expr
            )
        except Exception as e:
            logger.warning(f"Async векторный поиск упал: {e}")
            return []

    def get_chunks_by_parent_id(self, parent_id: str, limit: int = 10) -> List[dict]:
        """Multi-granularity retrieval: находит дочерние чанки по parent_id.

        Позволяет подняться по иерархии (модуль → класс → функция):
        если найден чанк с parent_id, можно запросить все его дочерние
        элементы и получить полный контекст.

        Args:
            parent_id: Хеш родительского элемента (md5).
            limit: Максимум результатов.

        Returns:
            Список чанков с текстом и метаданными.
        """
        if self.indexer.table is None:
            return []
        try:
            # Проверяем доступность таблицы
            try:
                if self.indexer.table.count_rows() == 0:
                    return []
            except Exception:
                return []

            df = (
                self.indexer.table.search()
                .where(f"parent_id = '{parent_id}'", prefilter=True)
                .limit(limit)
                .to_pandas()
            )
            results = []
            for _, row in df.iterrows():
                results.append(
                    {
                        "text": row["text"],
                        "text_full": row.get("text_full", row["text"]),
                        "metadata": {
                            "file": row["file_path"],
                            "chunk_index": row["chunk_index"],
                            "hierarchy_level": row.get("hierarchy_level", ""),
                            "layer": row.get("layer", ""),
                            "symbol_type": row.get("symbol_type", ""),
                        },
                    }
                )
            return results
        except Exception as e:
            logger.error(f"Ошибка get_chunks_by_parent_id: {e}")
            return []

    def _reciprocal_rank_fusion(
        self,
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
        scores: Dict[str, float] = {}
        results_map: Dict[str, dict] = {}

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
        sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[
            :limit
        ]

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

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        use_rrf: bool = True,
        expand: bool = True,
        since: Optional[str] = None,
        before: Optional[str] = None,
        layer: Optional[str] = None,
        intent_hint: str = "auto",
    ) -> List[dict]:
        """Гибридный поиск: комбинирует BM25 (sparse) и векторный (dense) поиск.

        Синхронная обёртка для обратной совместимости.
        Используйте hybrid_search_async() для async контекста.

        Args:
            since: ISO datetime — только чанки проиндексированные после
            before: ISO datetime — только чанки проиндексированные до
            layer: Фильтрация по архитектурному слою (core/mcp/utils/tests/...)
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Уже внутри event loop — запускаем в отдельном потоке
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self.hybrid_search_async(
                        query, limit, use_rrf, expand, since, before, layer, intent_hint
                    ),
                )
                return future.result(timeout=30)
        else:
            return asyncio.run(
                self.hybrid_search_async(
                    query, limit, use_rrf, expand, since, before, layer, intent_hint
                )
            )

    async def hybrid_search_async(
        self,
        query: str,
        limit: int = 5,
        use_rrf: bool = True,
        expand: bool = True,
        since: Optional[str] = None,
        before: Optional[str] = None,
        layer: Optional[str] = None,
        intent_hint: str = "auto",
    ) -> List[dict]:
        """Асинхронный гибридный поиск: BM25 + векторный + реранкинг.

        Args:
            layer: Фильтрация по архитектурному слою (core/mcp/utils/tests/...).
                   Если указан — поиск идёт ТОЛЬКО в этом слое.

        Алгоритм:
        1. (Опционально) Расширяем запрос синонимами через query expansion
        2. Выполняем BM25 поиск для точных совпадений терминов
        3. Выполняем векторный поиск для семантически релевантных результатов
        4. Объединяем через RRF (Reciprocal Rank Fusion) или реранкер
        5. Опциональный мульти-провайдерный реранкинг
        6. Фильтрация по indexed_at (since/before)

        Note:
            Все синхронные LanceDB/BM25 вызовы оборачиваются в asyncio.to_thread,
            чтобы не блокировать event loop при параллельных MCP-запросах.
        """
        if not query or not query.strip():
            return []

        # Строим filter_expr для LanceDB (если указан layer)
        filter_expr = f"layer = '{layer}'" if layer else ""

        # Query Expansion: генерируем варианты запроса
        if expand:
            query_variants = _expand_query(query, max_expansions=3)
        else:
            query_variants = [query]

        # === Multi-Bucket RAG (v2.6.0): Safety Cap для overfetch ===
        perf_config = get_config().performance
        # raw_limit всегда >= 1 и <= MAX_RERANKER_INPUT, даже при limit=0/1
        raw_limit = min(
            max(limit * perf_config.overfetch_factor, 1),
            MAX_RERANKER_INPUT,
        )

        # Собираем результаты от всех вариантов
        all_bm25_results = []
        all_dense_results = []

        for variant in query_variants:
            # BM25 поиск (sparse) — пост-фильтрация по layer
            bm25_results = await self._bm25_search_async(variant, limit=raw_limit)
            if layer:
                bm25_results = [
                    r
                    for r in bm25_results
                    if r.get("metadata", {}).get("layer") == layer
                ]
            all_bm25_results.extend(bm25_results)

            # Векторный поиск (dense) — с prefilter в LanceDB
            # (варианты синонимов дают те же эмбеддинги)
            if variant == query and not all_dense_results:
                try:
                    # Используем async embedder если доступен (и это реальная корутина, а не MagicMock)
                    embed_async = getattr(self.embedder, "embed_batch_async", None)
                    if embed_async is not None and inspect.iscoroutinefunction(
                        embed_async
                    ):
                        query_vectors = await embed_async([variant], is_query=True)
                        query_vector = query_vectors[0] if query_vectors else None
                    else:
                        query_vector = self.embedder.embed(variant)
                    if query_vector:
                        dense_results = await self._vector_search_async(
                            query_vector, limit=raw_limit, filter_expr=filter_expr
                        )
                        all_dense_results = [
                            r for r in dense_results if "error" not in r
                        ]
                except Exception as e:
                    logger.warning(f"Не удалось выполнить dense поиск: {e}")

        # Дедупликация BM25 результатов
        seen_keys = set()
        unique_bm25 = []
        for r in all_bm25_results:
            key = f"{r['metadata']['file']}:{r['metadata']['chunk_index']}"
            if key not in seen_keys:
                seen_keys.add(key)
                unique_bm25.append(r)

        if use_rrf:
            rrf_results = self._reciprocal_rank_fusion(
                unique_bm25, all_dense_results, raw_limit
            )
        else:
            reranked = self._reranker.rerank_results(
                query, unique_bm25, all_dense_results, limit=raw_limit
            )
            rrf_results = [
                {
                    "text": res["text"],
                    "metadata": res["metadata"],
                    "bm25_score": res.get("bm25_score", 0.0),
                    "dense_score": res.get("dense_score", 0.0),
                    "final_score": res.get("final_score", 0.0),
                }
                for res in reranked
            ]

        # === Multi-Bucket RAG: Soft Weighting + Cut to limit ===
        rrf_results = self._apply_bucket_weights(rrf_results, intent_hint)

        # === v3.0: Co-change boost (git coupling) ===
        rrf_results = self._apply_co_change_boost(rrf_results)

        # Сортируем и обрезаем (чистый Python, на 30 элементах — микросекунды)
        rrf_results.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
        pre_rerank_results = rrf_results[:limit]

        # Мульти-провайдерный реранкинг (Ollama / LM Studio) — опциональный
        # Реранкер перезаписывает final_score своими семантическими весами
        final_results = await self._apply_multi_reranker_async(
            query, pre_rerank_results, limit
        )

        # Фильтрация по времени (since/before) — чистый Python
        return _filter_by_time(final_results, since=since, before=before)

    @staticmethod
    def _apply_bucket_weights(
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

    # === mode=ask: генерация ответа через phi-4 ===
    async def ask_async(self, query: str, limit: int = 5) -> str:
        """mode=ask: поиск + генерация ответа через phi-4.

        Args:
            query: Поисковый запрос
            limit: Максимум чанков для контекста

        Returns:
            Ответ phi-4 с цитатами или fallback на обычный поиск.
        """
        try:
            # Шаг 1: ищем релевантные чанки
            results = await self.hybrid_search_async(
                query, limit=limit, intent_hint="auto"
            )
            if not results:
                return _(
                    "🔍 По запросу ничего не найдено (база пуста или эмбеддер недоступен)."
                )

            # Шаг 2: собираем контекст
            context_parts = []
            for i, r in enumerate(results, 1):
                file_path = r.get("metadata", {}).get("file", "unknown")
                text = r.get("text_full") or r.get("text", "")
                context_parts.append(f"[Чанк {i}] File: {file_path}\n```\n{text}\n```")
            context = "\n---\n".join(context_parts)

            # Шаг 3: системный промпт (phi-4-mini-instruct)
            # Температура минимальна, stop-токены предотвращают зацикливание/повторы.
            system_prompt = (
                "You are a precise coding assistant for the MSCodeBase repository.\n"
                "Rules:\n"
                "1. Answer ONLY from the provided code chunks.\n"
                "2. If the context does not contain the answer, write exactly: "
                "'В предоставленном контексте нет информации для ответа.'\n"
                "3. Cite files as (File: path).\n"
                "4. Answer in Russian, concisely, and stop after the answer.\n"
                "5. Do not repeat the question or add explanations beyond the answer.\n"
                "6. Do not invent code or facts not present in the context."
            )
            user_prompt = (
                f"Контекст кодовой базы:\n{context}\n\n"
                f"Вопрос: {query}\n\n"
                "Ответь кратко на русском языке, используя ТОЛЬКО контекст выше."
            )

            # Шаг 4: зовём phi-4 через LM Studio
            config = get_config()
            chat_url = (
                f"http://{config.embedding.lm_studio_host}:"
                f"{config.embedding.lm_studio_port}/v1/chat/completions"
            )
            payload = {
                "model": config.performance.ask_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 512,
                "stream": False,
                "stop": ["Контекст кодовой базы:", "Вопрос:", "\n\n\n"],
            }

            async with httpx.AsyncClient(
                timeout=config.performance.ask_timeout
            ) as client:
                resp = await client.post(chat_url, json=payload)
                if resp.status_code != 200:
                    logger.warning(
                        f"phi-4 вернул {resp.status_code}: {resp.text[:200]}"
                    )
                    return _("❌ LLM недоступен. Используйте mode=quality.")

                data = resp.json()
                answer = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if not answer:
                    return _("❌ LLM вернул пустой ответ.")

                return _(
                    "🤖 **Ответ (phi-4):**\n\n{answer}\n\n"
                    "---\n*Ответ сгенерирован на основе {count} чанков кодовой базы.*",
                    answer=answer,
                    count=len(results),
                )

        except httpx.TimeoutException:
            logger.warning(
                f"phi-4 timeout ({config.performance.ask_timeout}s) для запроса: {query[:80]}"
            )
            return _("❌ LLM не ответил за отведённое время. Попробуйте mode=quality.")
        except Exception as e:
            logger.error(f"Ошибка в ask_async: {e}")
            return _("❌ Ошибка генерации ответа: {error}", error=str(e))

    def search(
        self,
        query: str,
        limit: int = 5,
        since: Optional[str] = None,
        before: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> str:
        """Гибридный поиск для MCP-инструмента search_code.

        Args:
            query: Поисковый запрос
            limit: Максимум результатов
            since: ISO datetime — только чанки проиндексированные после
            before: ISO datetime — только чанки проиндексированные до
            layer: Фильтрация по архитектурному слою (core/mcp/utils/tests/...)
        """
        try:
            results = self.hybrid_search(
                query, limit=limit, since=since, before=before, layer=layer
            )
            if not results:
                return _(
                    "🔍 По запросу ничего не найдено (база пуста или эмбеддер недоступен)."
                )

            output = [
                f"📊 Найдено {len(results)} релевантных фрагментов кода (гибридный поиск):\n"
            ]
            for i, res in enumerate(results, 1):
                # Используем text_full если есть (полный код функции), иначе text
                code_text = res.get("text_full") or res["text"]
                output.append(
                    f"{i}. 📄 {res['metadata']['file']} [Чанк #{res['metadata']['chunk_index']}]\n"
                    f"```\n{code_text}\n```\n"
                    f"{'-' * 60}\n"
                )
            return "".join(output)
        except Exception as e:
            return _("❌ Search engine error: {error}", error=str(e))

    def search_with_mode(
        self,
        query: str,
        mode: str = "quality",
        limit: int = 5,
        layer: Optional[str] = None,
        intent_hint: str = "auto",
    ) -> Dict:
        """Поиск с выбором режима (fast/quality/deep).

        Args:
            query: Поисковый запрос
            mode: Режим поиска
                - fast: ~2300ms, только embedding + vector (ONNX CPU)
                - quality: ~5600ms, + reranker (ONNX CPU)
                - deep: ~2-5s, + graph analysis
                Timings with ONNX Runtime on CPU. LM Studio (GPU) can be faster.
            limit: Максимум результатов
            layer: Фильтрация по архитектурному слою (core/mcp/utils/tests/...)

        Returns:
            {
                results: [...],
                mode: str,
                timing_ms: {...},
                cache_hit: bool,
            }
        """
        import time

        t0 = time.perf_counter()
        timing = {}
        cache_hit = False

        # Проверяем кэш (изолируем по режиму, запросу, лимиту, слою и intent)
        cache_key = f"{mode}:{query}:{limit}:{layer or ''}:{intent_hint}"
        if cache_key in self._cache:
            results = self._cache[cache_key]
            cache_hit = True
            timing["total_ms"] = (time.perf_counter() - t0) * 1000
            return {
                "results": results,
                "mode": mode,
                "timing_ms": timing,
                "cache_hit": cache_hit,
                "model_info": self._multi_reranker.model_info
                if self._multi_reranker
                else "cached",
                "rerank_timing": getattr(self, "_last_rerank_timing", {}),
            }

        results = []

        filter_expr = f"layer = '{layer}'" if layer else ""

        if mode == self.MODE_FAST:
            # FAST: embed + vector only (без реранкера, но с bucketing)
            t1 = time.perf_counter()
            query_vector = self.embedder.embed(query)
            timing["embed_ms"] = (time.perf_counter() - t1) * 1000

            if query_vector:
                t1 = time.perf_counter()
                raw_results = self.vector_search(
                    query_vector, limit=limit, filter_expr=filter_expr
                )
                timing["search_ms"] = (time.perf_counter() - t1) * 1000
                # v2.6.0: Bucket weighting для fast mode
                results = self._apply_bucket_weights(raw_results, intent_hint)
                results.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
            else:
                results = []

        elif mode == self.MODE_DEEP:
            # DEEP: quality + graph context
            t1 = time.perf_counter()
            results = self.hybrid_search(
                query, limit=limit, layer=layer, intent_hint=intent_hint
            )
            timing["search_ms"] = (time.perf_counter() - t1) * 1000

            # Graph context expansion: добавляем связанные символы из графа вызовов
            t1 = time.perf_counter()
            results = self._expand_graph_context(results, query)
            timing["graph_expansion_ms"] = (time.perf_counter() - t1) * 1000

        else:
            # QUALITY (default): hybrid with rerank
            t1 = time.perf_counter()
            results = self.hybrid_search(
                query, limit=limit, layer=layer, intent_hint=intent_hint
            )
            timing["search_ms"] = (time.perf_counter() - t1) * 1000

            # Graph context expansion для quality mode (было только для deep)
            t1 = time.perf_counter()
            results = self._expand_graph_context(results, query)
            timing["graph_expansion_ms"] = (time.perf_counter() - t1) * 1000

        timing["total_ms"] = (time.perf_counter() - t0) * 1000

        # Сохраняем в кэш
        if len(self._cache) >= self._cache_max_size:
            # Удаляем самый старый
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        self._cache[cache_key] = results

        return {
            "results": results,
            "mode": mode,
            "timing_ms": timing,
            "cache_hit": cache_hit,
            "model_info": self._multi_reranker.model_info
            if self._multi_reranker
            else "no-reranker",
            "rerank_timing": getattr(self, "_last_rerank_timing", {}),
        }

    def context_search(self, selected_code: str, limit: int = 5) -> str:
        """Поиск похожего кода по выделенному фрагменту.

        Эмбеддит выделенный код и ищет семантически похожие чанки.
        Полезно для: поиска дубликатов, похожих реализаций, альтернативных подходов.

        Args:
            selected_code: Выделенный фрагмент кода
            limit: Максимальное число результатов
        """
        if not selected_code.strip():
            return _("❌ Empty code fragment for search.")

        try:
            query_vector = self.embedder.embed(selected_code)
            if not query_vector:
                return _("❌ Embedder unavailable. Cannot vectorize code.")

            results = self.vector_search(query_vector, limit=limit)
            results = [r for r in results if "error" not in r]

            if not results:
                return _("🔍 Similar code not found.")

            # Фильтруем точные совпадения (тот же текст = дубликат)
            unique_results = []
            seen_texts = set()
            for r in results:
                text_key = r["text"].strip()[:200]
                if (
                    text_key not in seen_texts
                    and r["text"].strip() != selected_code.strip()
                ):
                    seen_texts.add(text_key)
                    unique_results.append(r)

            if not unique_results:
                return _("🔍 Exact matches found, but no unique similar fragments.")

            output = [f"🔍 Найдено {len(unique_results)} похожих фрагментов кода:\n"]
            for i, res in enumerate(unique_results, 1):
                # Используем text_full если есть (полный код функции), иначе text
                code_text = res.get("text_full") or res["text"]
                output.append(
                    f"{i}. 📄 {res['metadata']['file']} [Чанк #{res['metadata']['chunk_index']}]\n"
                    f"```\n{code_text[:500]}\n```\n"
                    f"{'-' * 60}\n"
                )
            return "".join(output)
        except Exception as e:
            logger.error(f"Ошибка context_search: {e}")
            return _("❌ Code search error: {error}", error=str(e))

    def _extract_key_terms(self, results: List[dict], max_terms: int = 5) -> List[str]:
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
            "the",
            "a",
            "an",
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
            "could",
            "should",
            "may",
            "might",
            "shall",
            "can",
            "need",
            "dare",
            "ought",
            "used",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "out",
            "off",
            "over",
            "under",
            "again",
            "further",
            "then",
            "once",
            "here",
            "there",
            "when",
            "where",
            "why",
            "how",
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
            "but",
            "and",
            "or",
            "if",
            "while",
            "return",
            "def",
            "class",
            "import",
            "from",
            "self",
            "none",
            "true",
            "false",
            "pass",
            "that",
            "this",
            "it",
            "its",
            "what",
            "which",
            "who",
            "whom",
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

    def _generate_refined_query(
        self, original_query: str, key_terms: List[str], iteration: int
    ) -> str:
        """Генерирует уточнённый запрос на основе ключевых терминов.

        Стратегия:
        - Итерация 1: оригинальный запрос + топ-3 ключевых термина
        - Итерация 2: только ключевые термины (если первый поиск дал мало)

        Args:
            original_query: Оригинальный запрос
            key_terms: Извлечённые ключевые термины
            iteration: Номер итерации (1 или 2)

        Returns:
            Уточнённый запрос
        """
        if not key_terms:
            return original_query

        if iteration == 1:
            # Добавляем ключевые термины к оригинальному запросу
            top_terms = key_terms[:3]
            return f"{original_query} {' '.join(top_terms)}"
        else:
            # Вторая итерация: фокусируемся на ключевых терминах
            return " ".join(key_terms[:5])

    def agentic_deep_search(
        self,
        query: str,
        max_iterations: int = 3,
        limit_per_iteration: int = 5,
        max_total_results: int = 8,
    ) -> Tuple[List[dict], Dict[str, any]]:
        """Итеративный поиск с уточнением запроса (Agentic Deep Search).

        Алгоритм:
        1. Выполняет гибридный поиск с оригинальным запросом
        2. Анализирует результаты, извлекает ключевые термины
        3. Генерирует уточнённый запрос
        4. Повторяет поиск с уточнённым запросом
        5. Объединяет все результаты через RRF
        6. Останавливается при достижении max_iterations или достаточном числе результатов

        Args:
            query: Поисковый запрос
            max_iterations: Максимальное число итераций (по умолчанию 3)
            limit_per_iteration: Число результатов на итерацию
            max_total_results: Максимальное итоговое число результатов

        Returns:
            Tuple из (results, metadata) где metadata содержит информацию о поиске
        """
        all_results: List[dict] = []
        seen_keys: set = set()
        search_metadata = {
            "iterations": 0,
            "queries_used": [],
            "terms_extracted": [],
            "total_unique": 0,
            "early_stop": False,
        }

        current_query = query

        for iteration in range(1, max_iterations + 1):
            logger.debug(
                f"🔄 Agentic Deep Search: итерация {iteration}/{max_iterations}, "
                f"запрос: '{current_query[:60]}...'"
            )

            # Выполняем гибридный поиск
            results = self.hybrid_search(
                current_query,
                limit=limit_per_iteration,
                use_rrf=True,
                expand=(iteration == 1),  # Только первая итерация с query expansion
            )

            # Дедупликация
            new_results = []
            for r in results:
                key = f"{r['metadata']['file']}:{r['metadata']['chunk_index']}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    new_results.append(r)

            all_results.extend(new_results)
            search_metadata["iterations"] = iteration
            search_metadata["queries_used"].append(current_query[:80])

            logger.debug(
                f"  Итерация {iteration}: найдено {len(new_results)} новых, "
                f"всего {len(all_results)} уникальных"
            )

            # Проверка условия остановки: достаточно результатов
            if len(all_results) >= max_total_results:
                search_metadata["early_stop"] = True
                search_metadata["early_stop_reason"] = "enough_results"
                break

            # Если это не последняя итерация — уточняем запрос
            if iteration < max_iterations:
                if not results or len(new_results) == 0:
                    # Нет результатов — пробуем query expansion с другими синонимами
                    expanded = _expand_query(query, max_expansions=5)
                    if len(expanded) > 1:
                        current_query = expanded[min(iteration, len(expanded) - 1)]
                        search_metadata["queries_used"].append(
                            f"[expansion] {current_query[:80]}"
                        )
                        continue
                    else:
                        # Нечего расширять — стоп
                        search_metadata["early_stop"] = True
                        search_metadata["early_stop_reason"] = "no_new_results"
                        break

                # Извлекаем ключевые термины из новых результатов
                key_terms = self._extract_key_terms(new_results, max_terms=5)
                search_metadata["terms_extracted"].extend(key_terms[:3])

                if not key_terms:
                    # Нет терминов для уточнения — стоп
                    search_metadata["early_stop"] = True
                    search_metadata["early_stop_reason"] = "no_key_terms"
                    break

                # Генерируем уточнённый запрос
                current_query = self._generate_refined_query(
                    query, key_terms, iteration
                )

        # Финальная дедупликация через RRF (объединяем все итерации)
        if not all_results:
            return [], search_metadata

        # Ранжируем по final_score (уже вычислен в hybrid_search)
        all_results.sort(key=lambda r: r.get("final_score", 0.0), reverse=True)

        # Ограничиваем итоговый список
        final_results = all_results[:max_total_results]
        search_metadata["total_unique"] = len(seen_keys)

        return final_results, search_metadata

    def _decompose_query_with_llm(self, query: str) -> List[str]:
        """Декомпозирует сложный запрос на подзапросы через LLM.

        Пытается использовать LM Studio API для семантической декомпозиции.
        При недоступности LLM — fallback на правило-базированные эвристики.

        Стратегии (в порядке приоритета):
        1. Разделение по союзам: "и", "а", "также", "плюс", "&", ","
        2. Разделение по вопросам: "как", "где", "когда", "что"
        3. Извлечение ключевых существительных и глаголов
        4. LLM-декомпозиция через LM Studio API (опциональный fallback)

        Args:
            query: Сложный запрос

        Returns:
            Список подзапросов (2-4 штуки)
        """
        import re

        # Пустой или однословный запрос не требует декомпозиции
        if not query or not query.strip():
            return [query]
        if len(query.split()) <= 1:
            return [query]

        # Попытка 1: детерминированная правило-базированная декомпозиция
        # (быстрая, не требует сети и предсказуема в тестах/проде).

        # Стратегия 1: разделение по ключевым союзам и знакам
        separators = r"(?:\s+(?:и|а|также|плюс|а также|и также)\s+|\s*[,;]\s+(?:и |а |также |плюс )?)"
        parts = re.split(separators, query, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p and len(p.strip()) > 3]

        if len(parts) >= 2:
            return parts[:4]

        # Стратегия 2: анализ структуры запроса
        # "Как работает X и где проверяется Y" -> ["как работает X", "где проверяется Y"]
        question_patterns = [
            (
                r"как\s+(?:работает|обрабатывается|вызывается|используется)\s+(.+?)(?:\s+(?:и|а|также|где)\s+|$)",
                "как работает",
            ),
            (
                r"где\s+(?:проверяется|находится|вызывается|используется|обрабатывается)\s+(.+?)(?:\s+(?:и|а|также|как)\s+|$)",
                "где находится",
            ),
            (
                r"что\s+(?:делает|происходит|содержит)\s+(.+?)(?:\s+(?:и|а|также|где|как)\s+|$)",
                "что делает",
            ),
            (
                r"когда\s+(?:вызывается|происходит|срабатывает)\s+(.+?)(?:\s+(?:и|а|также|где|как)\s+|$)",
                "когда вызывается",
            ),
        ]

        subqueries = []
        remaining = query.lower()

        for pattern, _prefix in question_patterns:
            match = re.search(pattern, remaining)
            if match:
                subquery = match.group(0).strip()
                if len(subquery) > 5:
                    subqueries.append(subquery)
                    # Удаляем найденную часть из оставшегося
                    remaining = remaining[: match.start()] + remaining[match.end() :]
                    remaining = remaining.strip()

        if subqueries:
            # Добавляем оставшуюся часть если есть
            if remaining and len(remaining) > 5:
                subqueries.append(remaining)
            return subqueries[:4]

        # Стратегия 3: извлечение ключевых терминов и построение подзапросов
        # Извлекаем существительные (слово после "как", "где", "что")
        key_terms = re.findall(
            r"(?:как|где|что|когда|почему)\s+(\w+(?:\s+\w+){0,2})", query.lower()
        )
        if key_terms:
            return [f"{term} {query.split()[0]}" for term in key_terms[:3]]

        # ЛЛМ-декомпозиция только для достаточно сложных запросов (≥ 4 слов или ≥ 25 символов)
        if len(query.split()) < 4 and len(query) < 25:
            return [query]

        # Фоллбэк: LLM-декомпозиция только если правила ничего не дали
        llm_subqueries = self._try_llm_decompose(query)
        if llm_subqueries and len(llm_subqueries) >= 2:
            logger.debug(f"🧠 LLM декомпозиция: {len(llm_subqueries)} подзапросов")
            return llm_subqueries[:4]

        # Крайний фоллбэк: возвращаем оригинальный запрос
        return [query]

    async def _decompose_query_with_llm_async(self, query: str) -> List[str]:
        """Async-версия: не блокирует event loop при LLM-вызове."""
        import asyncio as _asyncio

        return await _asyncio.to_thread(self._decompose_query_with_llm, query)

    def _try_llm_decompose(self, query: str) -> Optional[List[str]]:
        """Пытается декомпозировать запрос через LM Studio API.

        Использует локальный LM Studio (конфигурируемый URL) для разбиения
        сложного запроса на семантически независимые подзапросы.

        Args:
            query: Сложный запрос для декомпозиции

        Returns:
            Список подзапросов или None при ошибке
        """
        try:
            import httpx

            # Проверяем доступность LM Studio
            from src.core.config import get_config

            config = get_config()
            lm_url = os.getenv(
                "LM_STUDIO_URL", config.embedding.get_lm_studio_base_url() + "/v1"
            )

            # Быстрая проверка живости (1 секунда)
            httpx.get(lm_url.replace("/v1", ""), timeout=1.0)

            # Запрос на декомпозицию
            system_prompt = (
                "You are a code search query decomposer. Given a complex query about code, "
                "split it into 2-4 independent sub-queries that can be searched separately.\n\n"
                "Rules:\n"
                "- Each sub-query should focus on ONE concept\n"
                "- Sub-queries must be independent (no shared context needed)\n"
                "- Use natural language, keep sub-queries under 15 words each\n"
                "- Return ONLY a JSON array of strings, no explanation\n\n"
                "Example:\n"
                'Input: "How does authentication work and where are permissions checked?"\n'
                'Output: ["authentication flow implementation", "permission checking locations"]\n'
            )

            response = httpx.post(
                f"{lm_url}/chat/completions",
                json={
                    "model": "local-model",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 200,
                },
                timeout=5.0,
            )

            if response.status_code != 200:
                logger.debug(f"LM Studio вернул статус {response.status_code}")
                return None

            # Парсим ответ
            result = response.json()
            content = (
                result.get("choices", [{}])[0].get("message", {}).get("content", "")
            )

            # Извлекаем JSON массив из ответа
            # LLM может вернуть ```json [...] ``` или просто [...]
            import json as json_module

            json_match = re.search(r"\[.*\]", content, re.DOTALL)
            if json_match:
                subqueries = json_module.loads(json_match.group())
                # Валидация: каждый подзапрос должен быть строкой 5-100 символов
                valid = [
                    sq.strip()
                    for sq in subqueries
                    if isinstance(sq, str) and 5 <= len(sq.strip()) <= 100
                ]
                if len(valid) >= 2:
                    return valid

            logger.debug(f"Не удалось распарсить ответ LLM: {content[:100]}")
            return None

        except ImportError:
            logger.debug("httpx не установлен, LLM-декомпозиция недоступна")
            return None
        except Exception as e:
            logger.debug(f"LLM-декомпозиция недоступна: {e}")
            return None

    def _analyze_subquery_relations(
        self,
        subqueries: List[str],
        subquery_results: Dict[str, List[dict]],
        symbol_index=None,
    ) -> Dict[str, any]:
        """Анализирует связи между результатами подзапросов.

        Ищет общие файлы, символы и зависимости между результатами
        разных подзапросов для формирования связного ответа.

        Если передан symbol_index — использует Call Graph для поиска
        связанных символов (определения, вызовы) в общих файлах.

        Args:
            subqueries: Список подзапросов
            subquery_results: {subquery: [results]}
            symbol_index: SymbolIndex для Call Graph (опционально)

        Returns:
            Словарь с анализом связей
        """
        analysis = {
            "common_files": [],
            "related_symbols": [],
            "call_graph_hints": [],
            "flow_description": "",
            "coverage_score": 0.0,
            "call_graph_depth": 0,
            "call_graph_nodes_count": 0,
        }

        # Собираем все файлы из результатов
        all_files: Dict[str, List[str]] = {}  # file -> [subqueries]
        for sq, results in subquery_results.items():
            for r in results:
                fp = r["metadata"]["file"]
                if fp not in all_files:
                    all_files[fp] = []
                all_files[fp].append(sq[:30])

        # Находим файлы, которые появились в результатах нескольких подзапросов
        common = [f for f, sqs in all_files.items() if len(set(sqs)) > 1]
        analysis["common_files"] = common[:10]

        # Вычисляем coverage score
        total_results = sum(len(r) for r in subquery_results.values())
        unique_files = len(all_files)
        if total_results > 0:
            # Чем больше уникальных файлов покрыто, тем выше score
            analysis["coverage_score"] = min(
                1.0, unique_files / max(len(subqueries), 1)
            )

        # Формируем описание потока
        if len(subqueries) > 1:
            analysis["flow_description"] = (
                f"Запрос разбит на {len(subqueries)} подзапросов. "
                f"Найдено {total_results} результатов в {unique_files} файлах. "
            )
            if common:
                analysis["flow_description"] += (
                    f"{len(common)} файлов пересекаются между подзапросами."
                )

        # Call Graph анализ через build_call_graph
        if symbol_index and hasattr(symbol_index, "build_call_graph"):
            try:
                nodes_count = 0
                max_depth = 0
                for file_path in common[:5]:  # Топ-5 общих файлов
                    # Получаем символы, определённые в этом файле
                    sym_names = symbol_index.get_symbols_in_file(file_path)
                    if not sym_names:
                        continue

                    for sym_name in sym_names[:3]:  # Топ-3 символа на файл
                        call_graph = symbol_index.build_call_graph(sym_name, depth=2)

                        # Собираем информацию об определении
                        if call_graph.get("definition"):
                            for defn in call_graph["definition"]:
                                analysis["related_symbols"].append(
                                    {
                                        "name": call_graph["symbol"],
                                        "file": defn.get("file", file_path),
                                        "line": defn.get("line", 0),
                                        "kind": defn.get("kind", "unknown"),
                                    }
                                )

                        # Собираем информацию о вызовах (callers + callees)
                        callers = call_graph.get("callers", [])
                        callees = call_graph.get("callees", [])
                        impact_files = call_graph.get("impact_files", [])

                        if callers or callees:
                            analysis["call_graph_hints"].append(
                                {
                                    "symbol": call_graph["symbol"],
                                    "callers_count": len(callers),
                                    "callees_count": len(callees),
                                    "impact_files_count": len(impact_files),
                                    "called_from": [
                                        c.get("file", "") for c in callers[:3]
                                    ],
                                    "calls_to": [
                                        c.get("symbol", "") for c in callees[:3]
                                    ],
                                }
                            )

                        # Подсчёт узлов графа
                        graph_nodes = (
                            len(call_graph.get("definition", []))
                            + len(callers)
                            + len(callees)
                        )
                        nodes_count += graph_nodes
                        # Определяем глубину: если есть indirect_caller — depth=2
                        has_indirect = any(
                            c.get("kind") == "indirect_caller" for c in callers
                        )
                        depth = 2 if has_indirect else 1
                        max_depth = max(max_depth, depth)

                analysis["call_graph_depth"] = max_depth
                analysis["call_graph_nodes_count"] = nodes_count
            except Exception as e:
                logger.debug(f"Call Graph анализ недоступен, fallback: {e}")
                # Fallback на упрощённый подход
                try:
                    for file_path in common[:5]:
                        sym_names = symbol_index.get_symbols_in_file(file_path)
                        for sym_name in sym_names[:2]:
                            refs = symbol_index.find_references(sym_name)
                            if refs:
                                analysis["call_graph_hints"].append(
                                    {
                                        "symbol": sym_name,
                                        "reference_count": len(refs),
                                        "referenced_in": [
                                            r.file_path for r in refs[:3]
                                        ],
                                    }
                                )
                except Exception as e2:
                    logger.debug(f"Fallback анализ тоже недоступен: {e2}")

        return analysis

    def _expand_graph_context(
        self, results: List[dict], original_query: str
    ) -> List[dict]:
        """Расширяет результаты контекстом из графа вызовов (v3.0).

        Для каждого результата добавляет в metadata:
        - callers: список функций, которые вызывают этот символ
        - callees: список функций, которые вызывает этот символ

        Вместо создания синтетических [CALLER]-записей (как было раньше)
        обогащает существующие метаданные — агент видит связи прямо
        в ответе search_code без лишних вызовов.
        """
        try:
            import json

            expanded_results = list(results)

            # SymbolIndex для поиска связей (ленивый, может быть None)
            si = (
                getattr(self.indexer, "_symbol_index", None)
                if hasattr(self.indexer, "_symbol_index")
                else None
            )
            if si is None:
                # Пробуем достать через indexer.searcher.symbol_index
                try:
                    si = getattr(self.indexer, "symbol_index", None)
                except Exception:
                    si = None

            if si is None or not hasattr(si, "find_references"):
                return results

            for r in results[:10]:  # только топ-10 результатов
                text = r.get("text", "")
                if not text:
                    continue

                # Извлекаем имя символа из текста чанка
                name = self._extract_symbol_name(text)
                if not name or len(name) < 2:
                    continue

                meta = r.get("metadata", {})
                if not isinstance(meta, dict):
                    meta = {}

                # Находим callers (кто вызывает этот символ)
                refs = si.find_references(name)
                callers_list = []
                for ref in refs[:3]:
                    if not ref.is_definition and ref.symbol != name:
                        callers_list.append({
                            "symbol": ref.symbol,
                            "file": ref.file_path,
                            "line": ref.line,
                        })
                if callers_list:
                    meta["callers"] = callers_list

                # Находим callees (что вызывает этот символ) из metadata
                callees_raw = meta.get("callees", "")
                if callees_raw and isinstance(callees_raw, str):
                    try:
                        callees_list = json.loads(callees_raw)
                        meta["callee_count"] = len(callees_list)
                    except (json.JSONDecodeError, TypeError):
                        pass

                r["metadata"] = meta

            return expanded_results
        except Exception as e:
            logger.debug(f"Graph context expansion error: {e}")
            return results

    def _extract_symbol_name(self, text: str) -> Optional[str]:
        """Извлекает имя символа из текста чанка."""
        import re

        # Patтерны для извлечения имен символов
        patterns = [
            r"def\s+(\w+)",  # def function_name
            r"class\s+(\w+)",  # class ClassName
            r"(\w+)\s*=\s*function",  # variable = function
            r"function\s+(\w+)",  # function name
            r"const\s+(\w+)\s*=",  # const variable =
            r"let\s+(\w+)\s*=",  # let variable =
            r"var\s+(\w+)\s*=",  # var variable =
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)

        return None

    def _ensure_multi_reranker(self) -> Optional[MultiProviderReranker]:
        """Ленивая синхронная инициализация мульти-провайдерного реранкера."""
        if self._multi_reranker_initialized:
            return self._multi_reranker

        self._multi_reranker_initialized = True
        try:
            reranker = MultiProviderReranker()
            asyncio.run(reranker.initialize())
            self._multi_reranker = reranker
            return reranker
        except Exception as e:
            logger.warning(f"Не удалось инициализировать MultiProviderReranker: {e}")
            self._multi_reranker = None
            return None

    async def _ensure_multi_reranker_async(self) -> Optional[MultiProviderReranker]:
        """Ленивая thread-safe async инициализация мульти-провайдерного реранкера.

        Перед инициализацией проверяет, запущен ли llama-server с --reranking.
        Если процесс выгружен (idle timeout) — запускает его по требованию.
        Если запуск не удался — возвращает None с логом ошибки.
        """
        if self._multi_reranker_initialized:
            return self._multi_reranker

        async with self._multi_reranker_lock:
            # Double-check после захвата блокировки
            if self._multi_reranker_initialized:
                return self._multi_reranker

            # ─── Убеждаемся, что llama-server с --reranking запущен ───
            try:
                from src.core.llama_runner import get_global_runner
                runner = get_global_runner()
                status = await runner.ensure_reranker_started()
                if not status["success"]:
                    logger.warning(
                        f"Реренкер недоступен: {status.get('error', 'неизвестная ошибка')}. "
                        f"Quality mode будет без реранкинга (BM25+RRF)."
                    )
                    self._multi_reranker = None
                    return None
                # ─── Передаём ПРАВИЛЬНЫЙ URL реранкера (порт 8081, не 8080) ───
                # MultiProviderReranker по умолчанию коннектится к порту
                # эмбеддера (8080), а --reranking живёт на RERANK_PORT (8081).
                reranker_url = runner.reranker_url
            except Exception as e:
                logger.warning(f"Не удалось проверить/запустить реранкер: {e}")
                # fall through — quality mode без реранкера

            try:
                reranker = MultiProviderReranker(llama_cpp_url=reranker_url)
                await reranker.initialize()
                self._multi_reranker = reranker
                return reranker
            except Exception as e:
                logger.warning(
                    f"Не удалось инициализировать MultiProviderReranker: {e}"
                )
                self._multi_reranker = None
                return None
            finally:
                self._multi_reranker_initialized = True

    def _apply_multi_reranker(
        self,
        query: str,
        rrf_results: List[dict],
        top_n: int,
    ) -> List[dict]:
        """Синхронная обёртка для мульти-провайдерного реранкинга."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self._apply_multi_reranker_async(query, rrf_results, top_n),
                )
                return future.result(timeout=35)
        else:
            return asyncio.run(
                self._apply_multi_reranker_async(query, rrf_results, top_n)
            )

    async def _apply_multi_reranker_async(
        self,
        query: str,
        rrf_results: List[dict],
        top_n: int,
    ) -> List[dict]:
        """Асинхронный мульти-провайдерный реранкинг."""
        self._last_rerank_timing = {}

        if not rrf_results:
            return rrf_results

        reranker = await self._ensure_multi_reranker_async()
        if reranker is None or not reranker.is_available:
            return rrf_results

        try:
            results = await reranker.rerank(query, rrf_results, top_n=top_n)
            if hasattr(reranker, "last_timing"):
                self._last_rerank_timing = reranker.last_timing
            return results
        except Exception as e:
            logger.warning(f"MultiProviderReranker ошибка: {e}. Fallback к RRF.")
            return rrf_results

    def agentic_code_search(
        self,
        query: str,
        symbol_index=None,
        max_subqueries: int = 4,
        limit_per_subquery: int = 5,
        max_total_results: int = 10,
    ) -> Tuple[List[dict], Dict[str, any]]:
        """Agentic Code Search с LLM-декомпозицией запроса.

        Синхронная обёртка для обратной совместимости.
        Используйте agentic_code_search_async() для async контекста.
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self.agentic_code_search_async(
                        query,
                        symbol_index,
                        max_subqueries,
                        limit_per_subquery,
                        max_total_results,
                    ),
                )
                return future.result(timeout=60)
        else:
            return asyncio.run(
                self.agentic_code_search_async(
                    query,
                    symbol_index,
                    max_subqueries,
                    limit_per_subquery,
                    max_total_results,
                )
            )

    async def agentic_code_search_async(
        self,
        query: str,
        symbol_index=None,
        max_subqueries: int = 4,
        limit_per_subquery: int = 5,
        max_total_results: int = 10,
    ) -> Tuple[List[dict], Dict[str, any]]:
        """Асинхронный Agentic Code Search с LLM-декомпозицией запроса.

        Алгоритм (на основе arxiv.org/abs/2505.14321):
        1. Декомпозиция запроса на подзапросы (LLM с fallback на правила)
        2. **Параллельный поиск через asyncio.gather** (без ThreadPoolExecutor)
        3. Анализ связей между результатами (общие файлы, символы)
        4. Агрегация через RRF
        5. Fallback к обычному поиску при плохой декомпозиции

        Args:
            query: Сложный запрос
            symbol_index: SymbolIndex для Call Graph (опционально)
            max_subqueries: Максимальное число подзапросов
            limit_per_subquery: Число результатов на подзапрос
            max_total_results: Максимальное итоговое число результатов

        Returns:
            Tuple из (results, metadata)
        """
        # Шаг 1: Декомпозиция запроса
        subqueries = (await self._decompose_query_with_llm_async(query))[
            :max_subqueries
        ]

        search_metadata = {
            "original_query": query,
            "subqueries": subqueries,
            "decomposition_method": "llm"
            if len(subqueries) >= 2 and subqueries != [query]
            else "rules",
            "subquery_results_count": {},
            "relations": None,
            "total_unique": 0,
            "fallback_used": False,
        }

        if len(subqueries) <= 1:
            # Простой запрос — используем обычный гибридный поиск
            results = await self.hybrid_search_async(query, limit=max_total_results)
            search_metadata["subquery_results_count"][query] = len(results)
            search_metadata["decomposition_method"] = "none"
            return results, search_metadata

        # Шаг 2: Параллельный поиск через asyncio.gather (без потоков!)
        subquery_results: Dict[str, List[dict]] = {}

        try:
            # Создаём задачи для параллельного выполнения
            tasks = [
                self.hybrid_search_async(
                    sq, limit=limit_per_subquery, use_rrf=True, expand=True
                )
                for sq in subqueries
            ]

            # Запускаем все задачи параллельно
            results_list = await asyncio.gather(*tasks, return_exceptions=True)

            # Обрабатываем результаты
            for sq, sq_results in zip(subqueries, results_list):
                if isinstance(sq_results, Exception):
                    logger.warning(
                        f"Поиск подзапроса '{sq[:30]}' дал ошибку: {sq_results}"
                    )
                    subquery_results[sq] = []
                    search_metadata["subquery_results_count"][sq[:40]] = 0
                else:
                    subquery_results[sq] = sq_results
                    search_metadata["subquery_results_count"][sq[:40]] = len(sq_results)

        except Exception as e:
            # Fallback: последовательный поиск при ошибке
            logger.warning(
                f"asyncio.gather ошибка ({e}), fallback на последовательный поиск"
            )
            for sq in subqueries:
                sq_results = await self.hybrid_search_async(
                    sq, limit=limit_per_subquery, use_rrf=True, expand=True
                )
                subquery_results[sq] = sq_results
                search_metadata["subquery_results_count"][sq[:40]] = len(sq_results)

        # Шаг 2.5: Fallback при плохой декомпозиции
        # Если ни один подзапрос не дал результатов — ищем оригинальный запрос
        total_subquery_results = sum(len(r) for r in subquery_results.values())
        if total_subquery_results == 0:
            logger.info("⚠️ Декомпозиция не дала результатов, fallback на обычный поиск")
            search_metadata["fallback_used"] = True
            results = await self.hybrid_search_async(query, limit=max_total_results)
            search_metadata["subquery_results_count"][f"[fallback] {query[:40]}"] = len(
                results
            )
            return results, search_metadata

        # Шаг 3: Дедупликация и сборка результатов
        all_results: List[dict] = []
        seen_keys: set = set()

        for sq in subqueries:
            for r in subquery_results.get(sq, []):
                key = f"{r['metadata']['file']}:{r['metadata']['chunk_index']}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_results.append(r)

        # Шаг 4: Анализ связей между результатами (с Call Graph если доступен)
        relations = self._analyze_subquery_relations(
            subqueries, subquery_results, symbol_index=symbol_index
        )
        search_metadata["relations"] = relations

        # Шаг 5: Ранжирование через RRF scores
        all_results.sort(key=lambda r: r.get("final_score", 0.0), reverse=True)
        final_results = all_results[:max_total_results]
        search_metadata["total_unique"] = len(seen_keys)

        # Шаг 6: Мульти-провайдерный реранкинг (опциональный, async)
        try:
            reranker = await self._ensure_multi_reranker_async()
            if reranker is not None and reranker.is_available and final_results:
                final_results = await reranker.rerank(
                    query, final_results, top_n=max_total_results
                )
                search_metadata["reranker_used"] = True
            else:
                search_metadata["reranker_used"] = False
        except Exception as e:
            logger.warning(f"Реранкинг в agentic_code_search_async пропущен: {e}")
            search_metadata["reranker_used"] = False

        return final_results, search_metadata

    def deep_search(self, query: str, limit: int = 8) -> str:
        """Agentic Deep Search для MCP-инструмента.

        Итеративный поиск с уточнением запроса на основе найденных результатов.
        Возвращает форматированную строку для MCP.

        Args:
            query: Поисковый запрос
            limit: Максимальное число результатов
        """
        try:
            results, metadata = self.agentic_deep_search(
                query,
                max_iterations=3,
                limit_per_iteration=max(5, limit),
                max_total_results=limit,
            )

            if not results:
                return _(
                    "🔍 По запросу ничего не найдено (база пуста или эмбеддер недоступен)."
                )

            output_lines = [
                f"🧠 Agentic Deep Search: найдено {len(results)} результатов "
                f"({metadata['iterations']} итераций, {metadata['total_unique']} уникальных)\n"
            ]

            # Показываем использованные запросы для прозрачности
            if len(metadata["queries_used"]) > 1:
                output_lines.append("📝 Использованные запросы:")
                for i, q in enumerate(metadata["queries_used"], 1):
                    output_lines.append(f"   {i}. {q}")
                output_lines.append("")

            for i, res in enumerate(results, 1):
                score = res.get("final_score", 0.0)
                # Используем text_full если есть (полный код функции), иначе text
                code_text = res.get("text_full") or res["text"]
                output_lines.append(
                    f"{i}. 📄 {res['metadata']['file']} [Чанк #{res['metadata']['chunk_index']}] "
                    f"(score={score:.4f})\n"
                    f"```\n{code_text}\n```\n"
                    f"{'-' * 60}\n"
                )

            return "".join(output_lines)
        except Exception as e:
            logger.error(f"Ошибка agentic_deep_search: {e}", exc_info=True)
            return _("❌ Deep search error: {error}", error=str(e))
