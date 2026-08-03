"""Диагностика: воспроизведение quality-пайплайна вне MCP (read-only).

Строит реальный Searcher с read-only LanceDB-таблицей и реальными
embedder/reranker (llama-server 8080/8081), гоняет hybrid_search_async
со стадиями и жёстким watchdog. Цель — найти стадию, которая висит >30с.
"""
import sys, os, time, asyncio, logging, json
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
# Тихие шумные логгеры
for noisy in ("httpx", "httpcore", "lancedb", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

sys.path.insert(0, r"D:\Project\MSCodeBase")
from pathlib import Path

DB_PATH = r"C:\Users\misha\AppData\Local\mscodebase\projects\bfe9644b\lancedb_v2\index_mscodebase_bfe9644b.db"
EMBED_URL = "http://127.0.0.1:8080/v1/embeddings"
RERANK_URL = "http://127.0.0.1:8081"

import httpx
import lancedb


class FakeIndexer:
    """Read-only обёртка над живой таблицей (НЕ захватывает PID-lock)."""

    def __init__(self, db_path: str):
        self.db = lancedb.connect(db_path)
        self.table = self.db.open_table("codebase_chunks")
        self.project_path = Path(r"D:\Project\MSCodeBase")
        self.db_manager = None

    async def search_async(self, query_vector, limit=5, filter_expr=""):
        search_obj = self.table.search(query_vector, vector_column_name="vector")
        if filter_expr:
            search_obj = search_obj.where(filter_expr, prefilter=True)
        df = search_obj.limit(limit).to_pandas()
        out = []
        for _, row in df.iterrows():
            out.append({
                "text": row["text"],
                "text_full": row.get("text_full", row["text"]),
                "score": row.get("_distance", 0.0),
                "final_score": row.get("_distance", 0.0),
                "metadata": {
                    "file": row["file_path"],
                    "chunk_index": row["chunk_index"],
                    "indexed_at": row.get("indexed_at", ""),
                    "layer": row.get("layer", ""),
                },
            })
        return out


class FakeEmbedder:
    """Реальный embedder через llama-server 8080."""

    async def embed_batch_async(self, texts, is_query=True):
        r = httpx.post(EMBED_URL, json={"input": list(texts)}, timeout=15)
        return [d["embedding"] for d in r.json()["data"]]

    def embed(self, text):
        r = httpx.post(EMBED_URL, json={"input": [text]}, timeout=15)
        return r.json()["data"][0]["embedding"]


class RealEmbedderProxy:
    """Реальный RemoteEmbedder (общий httpx.Client, как в MCP)."""

    def __init__(self):
        from src.providers.embedder.remote_embedder import RemoteEmbedder
        self._inner = RemoteEmbedder()
        print(f"[stage] Real RemoteEmbedder mode={self._inner.mode}")

    async def embed_batch_async(self, texts, is_query=True):
        return await self._inner.embed_batch_async(texts, is_query=is_query)

    def embed(self, text):
        return self._inner.embed(text)


class AsyncTableIndexer:
    """Имитация реального Indexer: async-таблица создана на loop A (main),
    а search_async вызывается из loop B (executor thread) — кросс-loop reuse.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.project_path = Path(r"D:\Project\MSCodeBase")
        self.db_manager = None
        self._async_table = None
        self._async_lock = None
        # sync-таблица как в Indexer
        db = lancedb.connect(db_path)
        self.table = db.open_table("codebase_chunks")

    async def init_async_table_on_loop_a(self):
        """Создаём async-таблицу в контексте loop A (как MCP при старте)."""
        import src.core.indexing.db_manager as dbm_mod
        async_db = await lancedb.connect_async(self.db_path)
        self._async_table = await async_db.open_table("codebase_chunks")
        print(f"[stage] AsyncTable created on loop A")

    async def _ensure_async_table(self):
        import asyncio
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        async with self._async_lock:
            if self._async_table is not None:
                return self._async_table
            async_db = await lancedb.connect_async(self.db_path)
            self._async_table = await async_db.open_table("codebase_chunks")
            return self._async_table

    async def search_async(self, query_vector, limit=5, filter_expr=""):
        table = await self._ensure_async_table()
        if table is None:
            return []
        builder = await table.search(query_vector, vector_column_name="vector")
        df = await builder.limit(limit).to_pandas()
        out = []
        for _, row in df.iterrows():
            out.append({
                "text": row["text"],
                "text_full": row.get("text_full", row["text"]),
                "metadata": {
                    "file": row["file_path"],
                    "chunk_index": row["chunk_index"],
                    "indexed_at": row.get("indexed_at", ""),
                    "layer": row.get("layer", ""),
                },
                "vector": row.get("vector"),
            })
        return out


USE_REAL_EMBEDDER = len(sys.argv) > 1 and sys.argv[1] == "real"
USE_ASYNC_TABLE = len(sys.argv) > 1 and "async" in sys.argv


async def main():
    from src.core.search.engine import Searcher
    from src.providers.reranker.multi_provider import MultiProviderReranker

    if USE_ASYNC_TABLE:
        indexer = AsyncTableIndexer(DB_PATH)
        # Создаём async-таблицу на loop A
        await indexer.init_async_table_on_loop_a()
        print(f"[stage] AsyncTable предсоздана на loop A — кросс-loop reuse включён")
    else:
        indexer = FakeIndexer(DB_PATH)
    embedder = RealEmbedderProxy() if USE_REAL_EMBEDDER else FakeEmbedder()
    searcher = Searcher(indexer, embedder)

    # Привязываем реальный реранкер напрямую (минуя ensure_reranker_started)
    reranker = MultiProviderReranker(llama_cpp_url=RERANK_URL)
    t0 = time.time()
    await reranker.initialize()
    print(f"[stage] MultiProviderReranker.initialize: {time.time()-t0:.2f}s "
          f"(lm={reranker.lm_studio_available}, ollama={reranker.ollama_available}, "
          f"llama_cpp={reranker.llama_cpp_available})")
    searcher._multi_reranker = reranker
    searcher._multi_reranker_initialized = True

    query = "PID lock stale process detection"
    print(f"[stage] running hybrid_search_async (async_table={USE_ASYNC_TABLE}, real_embedder={USE_REAL_EMBEDDER}): {query!r}")
    t1 = time.time()
    if USE_REAL_EMBEDDER or USE_ASYNC_TABLE:
        # Точный реальный путь: sync wrapper в отдельном потоке + asyncio.run
        import concurrent.futures
        _exec = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="search_sync")
        fut = _exec.submit(asyncio.run, searcher.hybrid_search_async(query, limit=6, use_rrf=True))
        results = fut.result(timeout=35)
    else:
        results = await asyncio.wait_for(
            searcher.hybrid_search_async(query, limit=6, use_rrf=True), timeout=35
        )
    dt = time.time() - t1
    print(f"[stage] hybrid_search_async DONE: {dt:.2f}s, {len(results)} results")
    if results:
        for r in results[:3]:
            meta = r.get("metadata", {})
            print(f"  - {meta.get('file')}:{meta.get('chunk_index')} score={r.get('final_score')}")


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "crossloop":
        # Специальный режим: initialize на loop A (закрыт), rerank на loop B
        import asyncio as _a
        from src.providers.reranker.multi_provider import MultiProviderReranker

        async def _init_on_loop_a():
            r = MultiProviderReranker(llama_cpp_url=RERANK_URL)
            await r.initialize()
            print(f"[stage] initialize на loop A: llama_cpp={r.llama_cpp_available}")
            return r

        print("[stage] CROSS-LOOP TEST: initialize на loop A, затем rerank на loop B")
        r = _a.run(_init_on_loop_a())
        print("[stage] loop A закрыт, запускаю rerank на loop B (fresh asyncio.run)")
        t0 = time.time()
        try:
            def _run_b():
                async def _rerank_b():
                    scores = await r.rerank("test query", [
                        {"text": "документ а", "metadata": {"file": "a.py", "chunk_index": 0}},
                        {"text": "документ б", "metadata": {"file": "b.py", "chunk_index": 0}},
                    ], top_n=2)
                    return scores
                return _a.run(_rerank_b())
            scores = _run_b()
            print(f"[stage] rerank на loop B DONE: {time.time()-t0:.2f}s, scores={scores}")
        except Exception as e:
            print(f"[stage] rerank на loop B exception: {e}")
        _sys.exit(0)

    if len(_sys.argv) > 1 and _sys.argv[1] == "fixedpath":
        # Симуляция ИСПРАВЛЕННОГО пути search_code: running loop в main,
        # search_with_mode через asyncio.to_thread (как в search_tools.py)
        import asyncio as _a
        from src.core.search.engine import Searcher

        async def _run_fixed_path():
            indexer = AsyncTableIndexer(DB_PATH)
            await indexer.init_async_table_on_loop_a()
            embedder = FakeEmbedder()
            searcher = Searcher(indexer, embedder)

            async def _simulate_execute():
                t0 = time.time()
                raw = await _a.to_thread(
                    searcher.search_with_mode,
                    "PID lock stale process detection",
                    "quality",
                    6,
                    None,
                    "auto",
                    False,
                )
                dt = time.time() - t0
                results = raw.get("results", []) if isinstance(raw, dict) else []
                print(f"[stage] FIXED-PATH search_with_mode через to_thread: {dt:.2f}s, {len(results)} results")
                if results:
                    for r in results[:3]:
                        m = r.get("metadata", {})
                        print(f"  - {m.get('file')}:{m.get('chunk_index')} score={r.get('final_score')}")

            try:
                await _a.wait_for(_simulate_execute(), timeout=35)
                print("[stage] ✅ FIXED-PATH OK")
            except _a.TimeoutError:
                print("[stage] ⚠️ FIXED-PATH HANG >35s")
                _sys.exit(2)

        _a.run(_run_fixed_path())
        _sys.exit(0)

    try:
        asyncio.run(main())
    except asyncio.TimeoutError:
        print("[stage] ⚠️ WATCHDOG: hybrid_search_async >35s — HANG CONFIRMED in pipeline")
        sys.exit(2)
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
