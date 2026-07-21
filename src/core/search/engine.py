import asyncio
import inspect
import json
import logging
import re
import threading
from typing import Any, Dict, List, Optional

import httpx

from src.config.settings import (
    MAX_RERANKER_INPUT,
    get_config,
)
from src.core.interfaces.searcher import ISearcher
from src.providers.reranker.multi_provider import MultiProviderReranker
from src.providers.reranker.search_result_reranker import SearchResultReranker
from src.utils.i18n import _
from .token_savings import calculate_token_savings

# ── Extracted sub-modules ──────────────────────────────────────
from .agentic_search import AgenticSearchMixin
from .bm25 import BM25Mixin
from .fts5_mixin import FTS5Mixin
from .scoring import (
    _apply_co_change_boost,
    apply_bucket_weights,
    apply_mmr_diversity,
    auto_detect_intent,
    reciprocal_rank_fusion,
    reciprocal_rank_fusion_3way,
)
from .trace import SearchTracer
from .utils import (
    _expand_query,
    _extract_key_terms,
    _extract_symbol_name,
    _filter_by_time,
)

__all__ = [
    "Searcher",
]
logger = logging.getLogger(__name__)


class Searcher(BM25Mixin, FTS5Mixin, ISearcher, AgenticSearchMixin):
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
        self._fts5 = None  # FTS5IndexManager (lazy)
        self._fts5_lock = threading.Lock()
        self._bm25_df: Any = None
        self._tokenizer_re = re.compile(r"\W+")
        self._reranker = SearchResultReranker(bm25_weight=0.3, dense_weight=0.7)
        self._multi_reranker: Optional[MultiProviderReranker] = None
        self._multi_reranker_initialized: bool = False
        self._multi_reranker_lock = asyncio.Lock()

        # ── Multi-level cache ──
        self._cache: Dict[str, List[dict]] = {}
        self._cache_max_size = 500  # было 100
        self._embedding_cache: Dict[int, List[float]] = {}  # hash(query) -> vector
        self._embedding_cache_max = 1000  # ~1MB для 768d векторов
        self._embedding_cache_lock = threading.Lock()
        self._reranker_cache: Dict[str, List[dict]] = {}  # hash(query+chunks) -> scores
        self._reranker_cache_max = 200
        self._reranker_cache_lock = threading.Lock()

    async def close(self) -> None:
        """Освобождает ресурсы реранкера и кэш.

        Безопасно для многократного вызова.
        """
        self._cache.clear()
        with self._embedding_cache_lock:
            self._embedding_cache.clear()
        with self._reranker_cache_lock:
            self._reranker_cache.clear()
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
            except Exception as _count_err:
                logger.debug(f"count_rows failed (empty index assumed): {_count_err}")
                return []

            search_obj = self.indexer.table.search(
                query_vector, vector_column_name="vector"
            )
            if filter_expr:
                search_obj = search_obj.where(filter_expr, prefilter=True)
            df = search_obj.limit(limit).to_pandas()

            results = []
            for _, row in df.iterrows():
                # LanceDB _distance = негативная косинусная дистанция
                # (чем больше, тем ближе). Нужна для bucket weighting
                # в fast mode — иначе все final_score=0.0 и docs не штрафуются.
                l2_score = row.get("_distance", 0.0)
                results.append(
                    {
                        "text": row["text"],
                        "text_full": row.get("text_full", row["text"]),
                        "score": l2_score,
                        "final_score": l2_score,
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
            except Exception as _count_err2:
                logger.debug(f"count_rows failed (empty index assumed): {_count_err2}")
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
        tracer: Optional[SearchTracer] = None,
    ) -> List[dict]:
        """Гибридный поиск: комбинирует BM25 (sparse) и векторный (dense) поиск.

        Синхронная обёртка для обратной совместимости.
        Используйте hybrid_search_async() для async контекста.

        Args:
            since: ISO datetime — только чанки проиндексированные после
            before: ISO datetime — только чанки проиндексированные до
            layer: Фильтрация по архитектурному слою (core/mcp/utils/tests/...)
        """
        # Reindex-guard (AGENTS.md §5.13): если index_project рвёт self.db
        # в executor-потоке, search fast-fail (пустой результат), а не падает
        # с RuntimeError 'Not found' (паттерн chunkhound SerialDatabaseExecutor/guard).
        # Reindex-guard (AGENTS.md §5.13): если index_project рвёт self.db
        # в executor-потоке, search fast-fail (пустой результат), а не падает
        # с RuntimeError 'Not found' (паттерн chunkhound SerialDatabaseExecutor/guard).
        # B4/B12: callable check вместо getattr safe-default — если is_reindexing
        # переименовали/убрали, мы узнаем об этом, а не молча теряем fast-fail.
        if self.indexer is not None and hasattr(self.indexer, "db_manager"):
            dbm = self.indexer.db_manager
            if dbm is not None:
                reindexing = getattr(dbm, "is_reindexing", None)
                if callable(reindexing) and reindexing():
                    logger.warning(
                        "hybrid_search: reindex in progress, fast-fail (retry in a few seconds)"
                    )
                    return []
                elif not callable(reindexing) and reindexing is not None:
                    logger.error(
                        "db_manager.is_reindexing is NOT callable — fast-fail DISABLED"
                    )

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
                        query, limit, use_rrf, expand, since, before, layer, intent_hint, tracer
                    ),
                )
                return future.result(timeout=30)
        else:
            return asyncio.run(
                self.hybrid_search_async(
                    query, limit, use_rrf, expand, since, before, layer, intent_hint, tracer
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
        tracer: Optional[SearchTracer] = None,
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
        all_fts5_results: List[dict] = []
        query_vector = None  # для MMR

        # ── Tracer: query expansion ──
        if tracer:
            tracer.record_query_expansion(query_variants)

        for variant in query_variants:
            # BM25 поиск (sparse) — пост-фильтрация по layer
            bm25_results = await self._bm25_search_async(variant, limit=raw_limit)
            if tracer:
                tracer.record_bm25_batch(bm25_results)
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
                    # ── Embedding cache ──
                    query_hash = hash(variant)
                    with self._embedding_cache_lock:
                        cached_vector = self._embedding_cache.get(query_hash)

                    if cached_vector is not None:
                        query_vector = cached_vector
                        logger.debug(f"[Cache] Embedding HIT: {variant[:40]}...")
                    else:
                        embed_async = getattr(self.embedder, "embed_batch_async", None)
                        if embed_async is not None and inspect.iscoroutinefunction(embed_async):
                            query_vectors = await embed_async([variant], is_query=True)
                            query_vector = query_vectors[0] if query_vectors else None
                        else:
                            query_vector = self.embedder.embed(variant)
                        if query_vector:
                            with self._embedding_cache_lock:
                                if len(self._embedding_cache) >= self._embedding_cache_max:
                                    self._embedding_cache.clear()
                                self._embedding_cache[query_hash] = query_vector
                        dense_results = await self._vector_search_async(
                            query_vector, limit=raw_limit, filter_expr=filter_expr
                        )
                        all_dense_results = [
                            r for r in dense_results if "error" not in r
                        ]
                    if tracer:
                        tracer.record_dense_batch(all_dense_results)
                except Exception as e:
                    logger.warning(f"Не удалось выполнить dense поиск: {e}")

        # FTS5 (full-text) — параллельно, с защитой от таймаута.
        # _fts5_search делает lazy build (to_pandas на весь индекс, ~0.5s на
        # первом вызове). Чтобы не усугублять 15s-лимит search_code, оборачиваем
        # в wait_for(2s): при превышении — degraded ([]), основной поиск жив.
        try:
            fts5_raw = await asyncio.wait_for(
                self._fts5_search_async(query, limit=raw_limit * 2),
                timeout=2.0,
            )
            all_fts5_results.extend(fts5_raw)
        except asyncio.TimeoutError:
            logger.warning("FTS5 search timed out (>2s), skipping FTS5 tier")
        except Exception as e:
            logger.debug(f"FTS5 search error: {e}")
        seen_keys = set()
        unique_bm25 = []
        for r in all_bm25_results:
            key = f"{r['metadata']['file']}:{r['metadata']['chunk_index']}"
            if key not in seen_keys:
                seen_keys.add(key)
                unique_bm25.append(r)

        if use_rrf:
            rrf_results = reciprocal_rank_fusion_3way(
                unique_bm25, all_dense_results, all_fts5_results, raw_limit
            )
            if tracer:
                tracer.record_rrf(rrf_results)
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

        # === v3.2.1: MMR diversification (убирает дубли, сохраняя релевантность) ===
        _mmr_before = list(rrf_results) if tracer else None
        rrf_results = apply_mmr_diversity(
            rrf_results,
            query_vector=query_vector,
            lambda_param=0.6,
            top_k=limit * 2,
        )
        if tracer and _mmr_before:
            tracer.record_mmr(_mmr_before, rrf_results, lambda_param=0.6)

        # === v3.2.1 B1: Auto-detect intent ===
        if intent_hint == "auto":
            intent_hint = auto_detect_intent(query)
            if intent_hint != "auto":
                logger.debug(f"[Intent] {query[:40]}... → {intent_hint}")

        # === Multi-Bucket RAG: Soft Weighting + Cut to limit ===
        rrf_results = apply_bucket_weights(rrf_results, intent_hint)
        if tracer:
            tracer.record_bucket(rrf_results, intent_hint)

        # === v3.0: Co-change boost (git coupling) ===
        # Копируем результаты перед модификацией для Co-change boost.
        # Используем id()-индекс для быстрого поиска (chunk может быть изменён _apply_co_change_boost).
        _cc_before = {id(r): dict(r) for r in rrf_results} if tracer else None
        rrf_results = self._apply_co_change_boost(rrf_results)
        if tracer and _cc_before:
            _boosts = {}
            for ch in rrf_results:
                key = f"{ch.get('metadata', {}).get('file', '?')}:{ch.get('metadata', {}).get('chunk_index', '?')}"
                before = _cc_before.get(id(ch), {}).get("final_score", 0) or 0
                after = ch.get("final_score", 0) or 0
                if before > 0:
                    _boosts[key] = after / before
                else:
                    _boosts[key] = 1.0
            tracer.record_co_change(rrf_results, _boosts)

        # Сортируем и обрезаем (чистый Python, на 30 элементах — микросекунды)
        rrf_results.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
        pre_rerank_results = rrf_results[:limit]

        # Мульти-провайдерный реранкинг (Ollama / LM Studio) — опциональный
        # Реранкер перезаписывает final_score своими семантическими весами
        _pre_rerank = list(pre_rerank_results) if tracer else None
        final_results = await self._apply_multi_reranker_async(
            query, pre_rerank_results, limit
        )
        if tracer and _pre_rerank:
            tracer.record_reranker(_pre_rerank, final_results)

        # Фильтрация по времени (since/before) — чистый Python
        if tracer:
            tracer.record_final(final_results)

        # ── v3.3.2: Token Savings (CRG pattern) ───────────────────────────────
        token_savings = calculate_token_savings(final_results)
        for r in final_results:
            r["_token_savings"] = token_savings

        return _filter_by_time(final_results, since=since, before=before)

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
        explain: bool = False,
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

        # ── Tracer for explainability ──
        tracer = SearchTracer(query, enabled=explain) if explain else None

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
                "trace": tracer.to_dict() if tracer else None,
            }

        results = []

        filter_expr = f"layer = '{layer}'" if layer else ""

        if mode == self.MODE_FAST:
            # FAST: embed + vector + FTS5 (без реранкера, но с bucketing)
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
                results = apply_bucket_weights(raw_results, intent_hint)
                results.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
            else:
                results = []

            # FTS5 (full-text) — синхронно (search_with_mode сам sync).
            # В fast-mode нет reranker, поэтому FTS5-метка гарантированно видна.
            # _fts5_search делает lazy build (~0.6s на первом вызове) — принимаем,
            # т.к. search_with_mode и так блокирующий (вызывается через asyncio.run).
            try:
                fts5_raw = self._fts5_search(query, limit=limit * 2)
                if fts5_raw:
                    # Сливаем dense + fts5 через 3-way RRF (bm25 пуст в fast-mode)
                    results = reciprocal_rank_fusion_3way([], results, fts5_raw, limit)
            except Exception as e:
                logger.debug(f"FTS5 search error in fast mode: {e}")

        elif mode == self.MODE_DEEP:
            # DEEP: quality + graph context
            t1 = time.perf_counter()
            results = self.hybrid_search(
                query, limit=limit, layer=layer, intent_hint=intent_hint, tracer=tracer
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
                query, limit=limit, layer=layer, intent_hint=intent_hint, tracer=tracer
            )
            timing["search_ms"] = (time.perf_counter() - t1) * 1000

            # Graph context expansion для quality mode (было только для deep)
            t1 = time.perf_counter()
            results = self._expand_graph_context(results, query)
            timing["graph_expansion_ms"] = (time.perf_counter() - t1) * 1000

        timing["total_ms"] = (time.perf_counter() - t0) * 1000

        # Сохраняем в кэш (без tracer чтобы не кэшировать explain-данные)
        if not explain:
            if len(self._cache) >= self._cache_max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[cache_key] = results

        # Добавляем trace в результат
        trace_dict = tracer.to_dict() if tracer else None
        if tracer:
            tracer.record_stage_timing("total_ms", timing.get("total_ms", 0))

        return {
            "results": results,
            "mode": mode,
            "timing_ms": timing,
            "cache_hit": cache_hit,
            "model_info": self._multi_reranker.model_info
            if self._multi_reranker
            else "no-reranker",
            "rerank_timing": getattr(self, "_last_rerank_timing", {}),
            "trace": trace_dict,
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
                # Smart truncation: up to 2000 chars
                if len(code_text) > 2000:
                    cut = code_text[:2000]
                    last_nl = cut.rfind("\n")
                    if last_nl > 1500:
                        cut = cut[:last_nl]
                    code_text = cut + "\n... [truncated]"
                output.append(
                    f"{i}. 📄 {res['metadata']['file']} [Chunk #{res['metadata']['chunk_index']}]\n"
                    f"```\n{code_text}\n```\n"
                    f"{'-' * 60}\n"
                )
            return "".join(output)
        except Exception as e:
            logger.error(f"Ошибка context_search: {e}")
            return _("❌ Code search error: {error}", error=str(e))







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
                except Exception as _si_err:
                    logger.debug(f"symbol_index fallback failed: {_si_err}")
                    si = None

            if si is None or not hasattr(si, "find_references"):
                return results

            for r in results[:10]:  # только топ-10 результатов
                text = r.get("text", "")
                if not text:
                    continue

                # Извлекаем имя символа из текста чанка
                name = _extract_symbol_name(text)
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
            reranker_url = None
            try:
                from src.providers.reranker.llama_runner import get_global_runner

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
        """Асинхронный мульти-провайдерный реранкинг с кэшем."""
        self._last_rerank_timing = {}

        if not rrf_results:
            return rrf_results

        # ── Reranker cache ──
        chunk_keys = "|".join(
            f"{r.get('metadata', {}).get('file', '')}:{r.get('metadata', {}).get('chunk_index', '')}"
            for r in rrf_results[:top_n]
        )
        cache_key = f"{hash(query)}:{hash(chunk_keys)}:{top_n}"

        with self._reranker_cache_lock:
            cached = self._reranker_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"[Cache] Reranker HIT: {len(cached)} results")
            return cached

        reranker = await self._ensure_multi_reranker_async()
        if reranker is None or not reranker.is_available:
            return rrf_results

        try:
            results = await reranker.rerank(query, rrf_results, top_n=top_n)
            if hasattr(reranker, "last_timing"):
                self._last_rerank_timing = reranker.last_timing
            # Сохраняем в кэш
            with self._reranker_cache_lock:
                if len(self._reranker_cache) >= self._reranker_cache_max:
                    self._reranker_cache.clear()
                self._reranker_cache[cache_key] = results
            return results
        except Exception as e:
            logger.warning(f"MultiProviderReranker ошибка: {e}. Fallback к RRF.")
            return rrf_results




# ── Assign scoring/utility functions as Searcher methods (backward compat) ──
Searcher._apply_co_change_boost = _apply_co_change_boost
Searcher._reciprocal_rank_fusion = staticmethod(reciprocal_rank_fusion)
Searcher._apply_bucket_weights = staticmethod(apply_bucket_weights)
Searcher._extract_key_terms = staticmethod(_extract_key_terms)
Searcher._extract_symbol_name = staticmethod(_extract_symbol_name)
