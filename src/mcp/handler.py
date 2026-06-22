"""
MSCodeBase Intelligence MCP Server - Главный обработчик (Handler)
Полная изоляция проектов, потокобезопасная очередь задач и фоновый обработчик индексации.
"""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mscodebase_server")

# --- Глобальное состояние сервера ---
embedder_instance = None
indexer_instance = None
searcher_instance = None

# Асинхронная очередь для фоновых задач индексации файлов
_task_queue: asyncio.Queue = asyncio.Queue()
_loop_instance: Optional[asyncio.AbstractEventLoop] = None

# Оркестратор: глобальный мьютекс защиты критических секций индексации всего проекта
_indexing_lock = threading.Lock()


async def background_worker():
    """
    Фоновый воркер (Consumer), последовательно обрабатывающий задачи из очереди.
    Исключает race conditions и перегрузку процессора при множественных изменениях файлов.
    """
    global indexer_instance
    logger.info("👷 Фоновый воркер обработки очереди задач успешно запущен.")

    while True:
        task_data = await _task_queue.get()
        try:
            task_type = task_data.get("type")
            file_path = Path(task_data.get("path"))

            if task_type == "file_changed" and indexer_instance:
                with _indexing_lock:
                    if file_path.exists():
                        logger.info(
                            f"🔄 Очередь: Инкрементальная переиндексация файла {file_path.name}"
                        )
                        indexer_instance.delete_file_from_index(file_path)

                        if indexer_instance.file_guard.is_supported(file_path):
                            with open(file_path, "rb") as f:
                                raw = f.read()
                            content = raw.decode("utf-8", errors="replace")
                            if content.strip():
                                parsed_chunks, _ = indexer_instance.parser.parse_file(
                                    file_path
                                )
                                chunks_text = (
                                    [c["text"] for c in parsed_chunks]
                                    if parsed_chunks
                                    else [content]
                                )
                                embs = indexer_instance.embedder.embed_batch(
                                    chunks_text
                                )
                                if embs and embs[0]:
                                    metas = [
                                        {
                                            "file_path": str(file_path),
                                            "chunk_index": idx,
                                        }
                                        for idx in range(len(chunks_text))
                                    ]
                                    ids = [
                                        f"queue_{hash(str(file_path))}_{idx}"
                                        for idx in range(len(chunks_text))
                                    ]
                                    indexer_instance.collection.upsert(
                                        ids=ids,
                                        embeddings=embs,
                                        documents=chunks_text,
                                        metadatas=metas,
                                    )
                                    if indexer_instance.searcher:
                                        indexer_instance.searcher.reindex()
                                    logger.info(
                                        f"✅ Файл {file_path.name} успешно обновлен из очереди."
                                    )
                    else:
                        logger.info(
                            f"🗑️ Очередь: Удаление файла {file_path.name} из векторного индекса"
                        )
                        indexer_instance.delete_file_from_index(file_path)
                        if indexer_instance.searcher:
                            indexer_instance.searcher.reindex()
        except Exception as e:
            logger.error(f"❌ Ошибка фонового воркера при обработке задачи: {e}")
        finally:
            _task_queue.task_done()


def submit_indexing_task(task_type: str, path_str: str):
    """
    Потокобезопасный метод добавления задач в очередь из любой точки (включая синхронный Watchdog)
    """
    global _loop_instance
    if _loop_instance and _loop_instance.is_running():
        asyncio.run_coroutine_threadsafe(
            _task_queue.put({"type": task_type, "path": path_str}),
            _loop_instance,
        )
        logger.debug(
            f"📥 Задача [{task_type}] поставлена в очередь для: {Path(path_str).name}"
        )


def create_mcp_server() -> FastMCP:
    """Фабрика для полной сборки и инициализации MCP сервера."""
    global embedder_instance, indexer_instance, searcher_instance, _loop_instance

    mcp = FastMCP("MSCodebase Intelligence Server")
    ext_root = Path(__file__).resolve().parent.parent.parent

    # Инициализация базовых модулей ядра
    from src.core.context_engine import get_context
    from src.core.file_guard import FileGuard
    from src.core.indexer import Indexer
    from src.core.remote_embedder import RemoteEmbedder
    from src.core.searcher import Searcher

    file_guard = FileGuard(project_path=ext_root)
    embedder_instance = RemoteEmbedder()

    db_dir = ext_root / ".codebase_indices" / "default_project"
    db_dir.mkdir(parents=True, exist_ok=True)

    indexer_instance = Indexer(
        db_path=db_dir, embedder=embedder_instance, file_guard=file_guard
    )
    searcher_instance = Searcher(indexer=indexer_instance, embedder=embedder_instance)
    indexer_instance.searcher = searcher_instance

    # --- ИНСТРУМЕНТЫ MCP ---

    @mcp.tool()
    def search_code(query: str, top_k: int = 5) -> str:
        """Гибридный поиск по всей кодовой базе проекта (Векторный + Ключевые слова)"""
        with _indexing_lock:
            if searcher_instance:
                return searcher_instance.search(query, top_k=top_k)
            return "❌ Поисковый движок не инициализирован."

    @mcp.tool()
    def get_context_tool(query: str, top_k: int = 5) -> str:
        """Cursor-like @codebase интеллектуальный сбор контекста под вопрос пользователя"""
        with _indexing_lock:
            if searcher_instance:
                return get_context(query, searcher=searcher_instance, top_k=top_k)
            return "❌ Контекстный движок недоступен."

    @mcp.tool()
    def index_project_status() -> str:
        """Возвращает текущий статус и наполнение локальной базы индексов"""
        if indexer_instance:
            stats = indexer_instance.get_status()
            return f"📊 Статус индекса:\n- Чанков в базе: {stats['total_chunks']}\n- Индексированных файлов: {stats['total_files']}\n- Путь к БД: {stats['db_path']}"
        return "❌ Ядро индексации недоступно."

    @mcp.tool()
    def force_reindex_all(project_path: str) -> str:
        """Принудительное полное перестроение поискового векторного индекса проекта"""

        def run_sync():
            with _indexing_lock:
                try:
                    indexer_instance.clear_index()
                    count = indexer_instance.index_project(Path(project_path))
                    logger.info(f"Фоновая переиндексация завершена. Файлов: {count}")
                except Exception as ex:
                    logger.error(f"Ошибка фоновой переиндексации: {ex}")

        threading.Thread(target=run_sync, daemon=True).start()
        return "🔄 Тяжелая задача полной переиндексации успешно запущена в фоне. Сервер продолжает отвечать на запросы."

    return mcp


def run_server(original_stdout=None):
    """Точка входа для запуска stdio сервера."""
    global _loop_instance
    mcp = create_mcp_server()
    if mcp:
        try:
            if original_stdout:
                sys.stdout = original_stdout

            _loop_instance = asyncio.get_event_loop()
            _loop_instance.create_task(background_worker())

            _loop_instance.run_until_complete(mcp.run_stdio_async())
        except KeyboardInterrupt:
            logger.info("Сервер остановлен пользователем.")
        except Exception as e:
            import traceback

            crash_log = (
                Path(__file__).resolve().parent.parent.parent / "crash_debug.log"
            )
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\nHandler crash:\n")
                traceback.print_exc(file=f)


if __name__ == "__main__":
    run_server()
