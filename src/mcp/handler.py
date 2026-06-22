"""
MSCodebase Intelligence MCP Server — Фоновый асинхронный воркер и полный набор из 6 инструментов MCP
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from src.core.file_guard import FileGuard
from src.core.indexer import Indexer
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher

# Безопасный импорт движков контекста и символов
try:
    from src.core.context_engine import get_context as get_context_func
    from src.core.symbol_index import SymbolIndex
except ImportError as e:
    logging.getLogger("mscodebase_server.handler").error(
        f"Ошибка импорта локальных модулей: {e}"
    )
    raise

logger = logging.getLogger("mscodebase_server.handler")

_task_queue: asyncio.Queue = None
_worker_task: asyncio.Task = None


async def background_queue_worker(indexer: Indexer, symbol_index: SymbolIndex):
    """
    Единственный потребитель задач индексации.
    Последовательно обновляет как векторный LanceDB индекс, так и структурный SymbolIndex.
    """
    logger.info("⚙️ Асинхронный Queue-воркер запущен и готов к обработке задач.")
    while True:
        project_path = await _task_queue.get()
        try:
            logger.info(
                f"🔄 Фоновый воркер: Старт полной индексации проекта: {project_path.name}"
            )

            # 1. Векторная индексация (выполняется в пуле потоков)
            await asyncio.to_thread(indexer.index_project, project_path)

            # 2. Структурный парсинг символов Tree-sitter (выполняется в пуле потоков)
            if hasattr(symbol_index, "index_project"):
                await asyncio.to_thread(symbol_index.index_project, project_path)

            logger.info(
                f"✅ Фоновый воркер: Проект {project_path.name} полностью синхронизирован (Векторы + Символы)."
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
    db_base_dir.mkdir(parents=True, exist_ok=True)

    # Инициализация компонентов ядра
    embedder = RemoteEmbedder(port=1234)
    file_guard = FileGuard(ext_root)
    indexer = Indexer(db_base_dir, embedder, file_guard)
    searcher = Searcher(indexer, embedder)
    indexer.searcher = searcher

    # ИСПРАВЛЕНО: SymbolIndex() не принимает аргументов (in-memory индекс)
    symbol_index = SymbolIndex()

    # ⚠️ ВАЖНО: Сюда нужно передать твой реальный объект парсера Tree-sitter!
    # Например: from src.core.parser import CodeParser; parser = CodeParser()
    # Пока ставим заглушку None, замени её на реальный экземпляр парсера.
    parser_instance = None

    def ensure_worker_started():
        global _task_queue, _worker_task
        if _task_queue is None:
            _task_queue = asyncio.Queue()
            _worker_task = asyncio.create_task(
                background_queue_worker(indexer, symbol_index)
            )
            logger.info(
                "⚡ Очередь asyncio.Queue и фоновый Task успешно инициализированы."
            )

    # 1. Инструмент MCP: Статус базы
    @mcp.tool()
    def get_index_status(**kwargs) -> str:
        """Возвращает текущую статистику заполнения векторной базы данных LanceDB и индекса символов."""
        stats = indexer.get_status()
        if "error" in stats:
            return f"❌ Ошибка получения статуса: {stats['error']}"

        total_symbols = (
            symbol_index.get_symbol_count()
            if hasattr(symbol_index, "get_symbol_count")
            else "N/A"
        )

        return (
            f"📊 Статус базы данных MSCodebase:\n"
            f"  • Всего фрагментов кода в базе (LanceDB): {stats.get('total_chunks', 0)}\n"
            f"  • Проиндексировано уникальных файлов: {stats.get('unique_files', 0)}\n"
            f"  • Найдено структурных символов (Tree-sitter): {total_symbols}\n"
            f"  • Состояние движка: {stats.get('status', 'unknown')}"
        )

    # 2. Инструмент MCP: Добавление проекта в очередь
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

    # 3. Инструмент MCP: Семантический поиск кусков кода
    @mcp.tool()
    def search_code(query: str, **kwargs) -> str:
        """Выполняет гибридный семантический поиск по фрагментам исходного кода проекта."""
        return searcher.search(query, limit=6)

    # 4. Инструмент MCP: Cursor @codebase Контекст-движок
    @mcp.tool()
    def get_context(query: str, **kwargs) -> str:
        """Генерирует интеллектуальный упакованный контекст для AI-ассистента в стиле Cursor @codebase."""
        return get_context_func(query, searcher)

    # 5. Инструмент MCP: Точный поиск определений и использований
    @mcp.tool()
    def get_symbol_info(query: str, **kwargs) -> str:
        """Ищет точные совпадения для определений и использований по их имени."""
        if not symbol_index:
            return "❌ Индекс символов не инициализирован."

        try:
            results = symbol_index.search_symbols(query)
            if not results:
                return f"🔍 Символ '{query}' не найден в структуре определений проекта."

            definitions = []
            usages = []

            # Корректно разделяем плоский список SymbolRef по признаку определения
            for res in results:
                if getattr(res, "is_definition", False):
                    definitions.append(res)
                else:
                    usages.append(res)

            output = [f"🗂️ Результаты анализа для символа '{query}':\n"]

            if definitions:
                output.append("📍 Определения:")
                for d in definitions:
                    output.append(
                        f"  • [{d.kind.upper()}] Файл: {d.file_path}:{d.line}"
                    )

            if usages:
                output.append("\n🔗 Использование в коде (Вызовы):")
                for u in usages:
                    output.append(f"  • Файл: {u.file_path}:{u.line}")

            return "\n".join(output)
        except Exception as e:
            logger.error(f"Ошибка при работе инструмента get_symbol_info: {e}")
            return f"❌ Ошибка при поиске информации о символе: {str(e)}"

    # 6. Инструмент MCP: Генерация читаемой Repo Map структуры
    @mcp.tool()
    def get_repo_map(project_root: str, **kwargs) -> str:
        """Возвращает текстовую карту репозитория: дерево файлов и ключевые символы."""
        if not symbol_index:
            return "❌ Движок анализа структуры недоступен."

        try:
            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь к проекту не найден: {project_root}"

            if hasattr(symbol_index, "get_repo_map"):
                raw_map = symbol_index.get_repo_map(str(target_path))

                output = [f"🗺️ Карта репозитория проекта: {target_path.name}\n"]
                output.append(
                    f"Всего отслеживаемых файлов: {raw_map.get('total_files', 0)}"
                )
                output.append(
                    f"Всего уникальных символов: {raw_map.get('total_symbols', 0)}\n"
                )
                output.append("📁 Структура и ключевые компоненты:")

                for item in raw_map.get("structure", []):
                    prefix = "  📄" if item["type"] == "file" else "  📁"
                    output.append(f"{prefix} {item['name']} ({item['path']})")

                    file_path = item["path"]
                    # Безопасно извлекаем символы, учитывая, что они могут быть как словарями, так и объектами
                    if file_path in raw_map.get("symbols_by_file", {}):
                        for sym in raw_map["symbols_by_file"][file_path]:
                            s_name = (
                                sym.get("name")
                                if isinstance(sym, dict)
                                else getattr(sym, "symbol", "unknown")
                            )
                            s_kind = (
                                sym.get("kind")
                                if isinstance(sym, dict)
                                else getattr(sym, "kind", "unknown")
                            )
                            output.append(f"      └─ [{s_kind.upper()}] {s_name}")

                return "\n".join(output)

            return f"🗺️ Карта проекта '{target_path.name}' (Символический индекс не поддерживает авто-маппинг)."
        except Exception as e:
            logger.error(f"Ошибка при работе инструмента get_repo_map: {e}")
            return f"❌ Ошибка генерации Repo Map: {str(e)}"

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
