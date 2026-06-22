"""
MSCodebase Intelligence MCP Server — Фоновый асинхронный брокер на базе неблокирующих очередей `asyncio.Queue`. Отрабатывает конкурентные запросы на индексацию от Zed IDE по паттерну Producer-Consumer.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from src.core.context_engine import get_context
from src.core.file_guard import FileGuard
from src.core.indexer import Indexer
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher
from src.core.symbol_index import SymbolIndex

logger = logging.getLogger("mscodebase_server.handler")

_task_queue: asyncio.Queue = None
_worker_task: asyncio.Task = None


async def background_queue_worker(indexer: Indexer):
    """Изолированный бесконечный потребитель задач в одном потоке Event Loop."""
    logger.info("⚙️ Асинхронный Queue-воркер запущен.")
    while True:
        project_path = await _task_queue.get()
        try:
            logger.info(
                f"🔄 Фоновый воркер: Старт индексации проекта: {project_path.name}"
            )
            await asyncio.to_thread(indexer.index_project, project_path)
            logger.info(
                f"✅ Фоновый воркер: Индексация проекта {project_path.name} успешно завершена."
            )
        except Exception as e:
            logger.error(
                f"❌ Критическая ошибка выполнения внутри воркера: {e}", exc_info=True
            )
        finally:
            _task_queue.task_done()


def create_mcp_server() -> FastMCP:
    mcp = FastMCP("MSCodebase Intelligence Server")
    ext_root = Path(__file__).resolve().parent.parent.parent
    db_base_dir = ext_root / ".codebase_indices" / "lancedb_v2"

    embedder = RemoteEmbedder(port=1234)
    file_guard = FileGuard()
    indexer = Indexer(db_base_dir, embedder, file_guard)
    searcher = Searcher(indexer, embedder)
    indexer.searcher = searcher
    symbol_indexer = SymbolIndex()

    def ensure_worker_started():
        global _task_queue, _worker_task
        if _task_queue is None:
            _task_queue = asyncio.Queue()
            _worker_task = asyncio.create_task(background_queue_worker(indexer))
            logger.info(
                "⚡ Очередь asyncio.Queue и фоновый Task успешно инициализированы."
            )

    @mcp.tool()
    def get_index_status(**kwargs) -> str:
        """Возвращает текущую статистику заполнения векторной базы данных LanceDB."""
        stats = indexer.get_status()
        if "error" in stats:
            return f"❌ Ошибка получения статуса: {stats['error']}"
        return (
            f"📊 Статус базы данных MSCodebase:\n"
            f"  • Всего фрагментов кода в базе: {stats.get('total_chunks', 0)}\n"
            f"  • Проиндексировано уникальных файлов: {stats.get('unique_files', 0)}\n"
            f"  • Состояние движка: {stats.get('status', 'unknown')}"
        )

    @mcp.tool()
    async def index_project_dir(path: str, **kwargs) -> str:
        """Добавляет директорию проекта в неблокирующую очередь задач на фоновую синхронизацию."""
        ensure_worker_started()
        target_path = Path(path).resolve()
        if not target_path.exists():
            return f"❌ Указанный путь не существует: {path}"

        await _task_queue.put(target_path)
        return (
            f"🚀 Проект '{target_path.name}' успешно добавлен в очередь на фоновую индексацию.\n"
            f"Задач ожидает в очереди: {_task_queue.qsize()}"
        )

    @mcp.tool()
    def search_code(query: str, **kwargs) -> str:
        """Выполняет гибридный поиск по фрагментам исходного кода проекта."""
        return searcher.search(query, limit=6)

    @mcp.tool()
    def get_context(query: str, **kwargs) -> str:
        """Генерирует интеллектуальный упакованный контекст для AI-ассистента в стиле Cursor @codebase."""
        from src.core.context_engine import get_context as get_context_func

        return get_context_func(query, searcher)

    @mcp.tool()
    def get_symbol_info(query: str, **kwargs) -> str:
        """Находит определения и использования функций, классов или методов по их имени."""
        if not symbol_indexer:
            return "❌ Индекс символов не инициализирован или отключен."

        results = symbol_indexer.search_symbols(query, top_k=5)
        if not results:
            return f"🔍 Символ '{query}' не найден в структуре проекта."

        output = [f"🗂️ Найдено совпадений для символа '{query}':\n"]
        for res in results:
            output.append(f"• Название: {res.get('symbol')}")
            # Показываем определения и количество использований
            defs = res.get("defined_in", [])
            if defs:
                output.append(f"  Определения:")
                for d in defs[:3]:  # Показываем до 3 определений
                    output.append(
                        f"    - {d.get('file')}:{d.get('line')} ({d.get('kind')})"
                    )
            output.append(f"  Используется в {res.get('used_in_count', 0)} файлах")
            if res.get("used_in_files"):
                output.append(
                    f"  Файлы использования: {', '.join(res['used_in_files'][:5])}"
                )
            output.append("")
        return "\n".join(output)

    @mcp.tool()
    def get_repo_map(project_root: str = ".", **kwargs) -> str:
        """Возвращает карту репозитория: структуру директорий + символы в файлах.

        Args:
            project_root: Корневая директория проекта (по умолчанию ".").

        Returns:
            JSON-подобная структура с ключами:
            - "structure": список директорий и файлов
            - "symbols_by_file": словарь file_path -> список символов
            - "all_symbols": список всех уникальных символов
            - "total_files": общее количество файлов
            - "total_symbols": общее количество символов
        """
        if not symbol_indexer:
            return "❌ Индекс символов не инициализирован или отключен."

        try:
            repo_map = symbol_indexer.get_repo_map(project_root)

            # Форматируем красиво для MCP
            output = ["🗺️ Карта репозитория MSCodebase:\n"]
            output.append(f"📁 Всего файлов: {repo_map['total_files']}")
            output.append(f"🔤 Всего символов: {repo_map['total_symbols']}\n")

            output.append("📂 Структура директорий:")
            for item in repo_map["structure"]:
                if item["type"] == "directory":
                    output.append(f"  📁 {item['path']}/")
                else:
                    output.append(f"  📄 {item['path']}")

            output.append("\n🔍 Символы по файлам:")
            for file_path, symbols in repo_map["symbols_by_file"].items():
                if symbols:
                    output.append(f"\n  📄 {file_path}:")
                    for sym in symbols[:5]:  # Показываем до 5 символов на файл
                        defs = sym.get("definitions", [])
                        refs = sym.get("references", [])
                        output.append(f"    • {sym['name']} ({sym['kind']})")
                        if defs:
                            def_lines = ", ".join([f"{d['line']}" for d in defs])
                            output.append(f"      Определения: {def_lines}")
                        if refs:
                            output.append(f"      Использования: {len(refs)} раз(а)")

            if repo_map["all_symbols"]:
                output.append(f"\n📋 Все символы ({len(repo_map['all_symbols'])}):")
                output.append(f"  {', '.join(repo_map['all_symbols'][:20])}")
                if len(repo_map["all_symbols"]) > 20:
                    output.append(f"  ... и еще {len(repo_map['all_symbols']) - 20}")

            return "\n".join(output)

        except Exception as e:
            logger.error(f"Ошибка получения карты репозитория: {e}")
            return f"❌ Ошибка получения карты репозитория: {e}"

    return mcp


def run_server(original_stdout=None):
    mcp = create_mcp_server()
    if mcp:
        try:
            if original_stdout:
                sys.stdout = original_stdout
            asyncio.run(mcp.run_stdio_async())
        except KeyboardInterrupt:
            logger.info("Сервер остановлен пользователем.")
        except Exception as e:
            logger.critical(f"Критический сбой MCP-сервера: {e}", exc_info=True)
