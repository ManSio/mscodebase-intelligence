"""
MSCodeBase Intelligence MCP Server — Главный обработчик.
Реализует паттерн Producer-Consumer через асинхронную очередь и двухуровневый граф контекста.
"""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mscodebase_server")

# --- Глобальные инстансы архитектуры ---
embedder_instance = None
indexer_instance = None
searcher_instance = None

# Потокобезопасная асинхронная очередь задач
_task_queue: asyncio.Queue = asyncio.Queue()
_loop_instance: Optional[asyncio.AbstractEventLoop] = None
_indexing_lock = threading.Lock()


async def background_worker():
    """
    Фоновый Consumer. Последовательно забирает задачи из очереди.
    Исключает гонку потоков при сохранении файлов в Zed.
    """
    global indexer_instance
    logger.info("👷 Фоновый воркер асинхронной очереди задач (LanceDB Engine) запущен.")

    while True:
        task_data = await _task_queue.get()
        try:
            task_type = task_data.get("type")
            file_path = Path(task_data.get("path"))

            if not indexer_instance:
                continue

            with _indexing_lock:
                if task_type == "file_changed":
                    if file_path.exists() and indexer_instance.file_guard.is_supported(
                        file_path
                    ):
                        logger.info(
                            f"🔄 Инкрементальное обновление графа для: {file_path.name}"
                        )
                        indexer_instance.delete_file_from_index(file_path)

                        try:
                            with open(file_path, "rb") as f:
                                raw = f.read()
                            content = raw.decode("utf-8", errors="replace")

                            parsed_chunks, _ = indexer_instance.parser.parse_file(
                                file_path
                            )
                            chunks_text = (
                                [c["text"] for c in parsed_chunks]
                                if parsed_chunks
                                else [content]
                            )

                            embs = indexer_instance.embedder.embed_batch(chunks_text)
                            if embs and embs[0]:
                                records = []
                                for idx, emb in enumerate(embs):
                                    chunk_meta = (
                                        parsed_chunks[idx] if parsed_chunks else {}
                                    )
                                    records.append(
                                        {
                                            "vector": emb,
                                            "id": f"watch_{hash(str(file_path))}_{idx}",
                                            "document": chunks_text[idx],
                                            "file_path": str(file_path),
                                            "chunk_index": idx,
                                            "start_line": int(
                                                chunk_meta.get("start_line", 0)
                                            ),
                                            "end_line": int(
                                                chunk_meta.get("end_line", 0)
                                            ),
                                            "type": str(
                                                chunk_meta.get("type", "code_block")
                                            ),
                                            "symbol_name": str(
                                                chunk_meta.get("symbol_name", "")
                                            ),
                                            "parent_symbol": "",
                                        }
                                    )
                                indexer_instance.table.add(records)
                                if indexer_instance.searcher:
                                    indexer_instance.searcher.reindex()
                                logger.info(
                                    f"✅ Файл {file_path.name} атомарно обновлен в LanceDB."
                                )
                        except Exception as e:
                            logger.error(
                                f"Не удалось обновить файл {file_path.name}: {e}"
                            )

                elif task_type == "file_deleted":
                    logger.info(f"🗑️ Удаление из графа LanceDB: {file_path.name}")
                    indexer_instance.delete_file_from_index(file_path)
                    if indexer_instance.searcher:
                        indexer_instance.searcher.reindex()

        except Exception as e:
            logger.error(f"Ошибка выполнения фоновой задачи: {e}")
        finally:
            _task_queue.task_done()


def submit_indexing_task(task_type: str, path_str: str):
    """Публикация задачи в очередь (вызывается из вотчера Watchdog)."""
    global _loop_instance
    if _loop_instance and _loop_instance.is_running():
        asyncio.run_coroutine_threadsafe(
            _task_queue.put({"type": task_type, "path": path_str}), _loop_instance
        )
        logger.debug(f"📥 Путь добавлен в очередь воркера: {Path(path_str).name}")


def create_mcp_server() -> FastMCP:
    """Сборка MCP сервера на базе локального LanceDB графа."""
    global embedder_instance, indexer_instance, searcher_instance

    mcp = FastMCP("MSCodebase Intelligence Server")
    ext_root = Path(__file__).resolve().parent.parent.parent

    from src.core.file_guard import FileGuard
    from src.core.indexer import Indexer
    from src.core.remote_embedder import RemoteEmbedder

    file_guard = FileGuard(project_path=ext_root)
    embedder_instance = RemoteEmbedder()

    # Директория для хранения LanceDB данных внутри плагина
    db_dir = ext_root / ".codebase_indices" / "lancedb_v2"

    indexer_instance = Indexer(
        db_path=db_dir, embedder=embedder_instance, file_guard=file_guard
    )

    @mcp.tool()
    def search_code(query: str, top_k: int = 3) -> str:
        """Двухуровневый семантический поиск по графу кодовой базы"""
        with _indexing_lock:
            if not indexer_instance:
                return "❌ Сервер не готов."
            try:
                query_vector = embedder_instance.embed(query)
                if not query_vector:
                    return "⚠️ Не удалось получить эмбеддинг запроса."

                results = (
                    indexer_instance.table.search(query_vector).limit(top_k).to_pandas()
                )

                if results.empty:
                    return "Ничего не найдено."

                formatted_output = []
                for _, row in results.iterrows():
                    output_block = f"📄 Файл: {row['file_path']} (Линии: {row['start_line']}-{row['end_line']})\n"
                    output_block += (
                        f"Type: {row['type']} | Symbol: {row['symbol_name']}\n"
                    )

                    if row["parent_symbol"] and row["type"] in [
                        "method_definition",
                        "method_declaration",
                    ]:
                        parent_cls = row["parent_symbol"]
                        output_block += f"ℹ️ Контекст: Метод принадлежит классу/структуре `{parent_cls}`\n"

                    output_block += f"```\n{row['document']}\n```\n"
                    formatted_output.append(output_block)

                return f"📊 Найденный семантический контекст:\n\n" + "\n".join(
                    formatted_output
                )
            except Exception as e:
                return f"❌ Ошибка выполнения гибридного поиска: {e}"

    @mcp.tool()
    def index_status() -> str:
        """Статус базы данных LanceDB"""
        if indexer_instance:
            stats = indexer_instance.get_status()
            return f"📊 Статус LanceDB индекса:\n- Всего семантических чанков: {stats['total_chunks']}\n- Уникальных файлов в графе: {stats['total_files']}\n- Движок: {stats['engine']}"
        return "❌ Ядро недоступно."

    @mcp.tool()
    def reindex_all(project_path: str) -> str:
        """Полная переиндексация проекта в фоновом системном потоке"""

        def run_sync():
            with _indexing_lock:
                try:
                    indexer_instance.clear_index()
                    indexer_instance.index_project(Path(project_path))
                except Exception as ex:
                    logger.error(f"Ошибка переиндексации: {ex}")

        threading.Thread(target=run_sync, daemon=True).start()
        return "🔄 Перестроение графа LanceDB запущено в фоновом потоке."

    @mcp.tool()
    def get_context_tool(query: str, top_k: int = 5) -> str:
        """Интеллектуальный сбор контекста из кода под вопрос AI-агента"""
        with _indexing_lock:
            if not indexer_instance:
                return "❌ Сервер не готов."
            try:
                query_vector = embedder_instance.embed(query)
                if not query_vector:
                    return "⚠️ Не удалось получить эмбеддинг запроса."

                results = (
                    indexer_instance.table.search(query_vector).limit(top_k).to_pandas()
                )

                if results.empty:
                    return "Контекст не найден."

                blocks = []
                for _, row in results.iterrows():
                    blocks.append(
                        f"Файл: {row['file_path']}:{row['start_line']}-{row['end_line']}\n"
                        f"```\n{row['document']}\n```"
                    )

                return "📚 Контекст из кодовой базы:\n\n" + "\n\n".join(blocks)
            except Exception as e:
                return f"❌ Ошибка: {e}"

    @mcp.tool()
    def file_search(pattern: str) -> str:
        """Поиск файлов по имени внутри индекса"""
        try:
            df = indexer_instance.table.to_pandas()
            matches = df[df["file_path"].str.contains(pattern, case=False, na=False)]
            files = matches["file_path"].unique()
            if len(files) == 0:
                return f"🔍 Файлы по маске '{pattern}' не найдены."
            return f"🔍 Найдено файлов ({len(files)}):\n" + "\n".join(sorted(files))
        except Exception as e:
            return f"❌ Ошибка поиска: {e}"

    return mcp


async def run_server_async():
    """Асинхронный запуск MCP сервера с фоновым воркером."""
    global _loop_instance
    _loop_instance = asyncio.get_running_loop()
    _loop_instance.create_task(background_worker())
    mcp = create_mcp_server()
    if mcp:
        await mcp.run_stdio_async()


def run_server(original_stdout=None):
    """Запуск stdio MCP-сервера."""
    global _loop_instance
    mcp = create_mcp_server()
    if mcp:
        try:
            if original_stdout:
                sys.stdout = original_stdout

            async def main():
                global _loop_instance
                _loop_instance = asyncio.get_event_loop()
                _loop_instance.create_task(background_worker())
                await mcp.run_stdio_async()

            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("Сервер остановлен.")
        except Exception as e:
            import traceback

            crash_log = (
                Path(__file__).resolve().parent.parent.parent / "crash_debug.log"
            )
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\nHandler Crash:\n")
                traceback.print_exc(file=f)


if __name__ == "__main__":
    run_server()
