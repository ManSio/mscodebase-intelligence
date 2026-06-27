"""MSCodebase Intelligence MCP Server - Чистый набор инструментов без поллинга файловой системы"""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.file_guard import FileGuard
from src.core.indexer import Indexer
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher

try:
    from src.core.context_engine import get_context as get_context_func
    from src.core.parser import CodeParser
    from src.core.symbol_index import SymbolIndex
except ImportError as e:
    logging.getLogger("mscodebase_server").error(
        f"Ошибка импорта локальных модулей: {e}"
    )
    raise

logger = logging.getLogger("mscodebase_server")

_task_queue: Optional[asyncio.Queue] = None
_worker_task: Optional[asyncio.Task] = None
_last_index_error: Optional[str] = None
_task_events: list = []


def _signal_all_events():
    """Сигналит всем ожидающим событиям о завершении задачи."""
    events = _task_events[:]
    for ev in events:
        ev.set()


async def background_queue_worker(
    indexer: Indexer, symbol_index: SymbolIndex, parser: "CodeParser"
):
    """
    Потребитель задач ПЕРВИЧНОЙ полной индексации.
    Последовательно обновляет векторный LanceDB индекс и структурный SymbolIndex.
    Больше не запускает никаких Watcher-потоков - LSP следит за файлами.
    """
    global _last_index_error
    logger.info("⚙️ Асинхронный Queue-воркер готов к тяжелой первичной индексации.")
    while True:
        project_path = await _task_queue.get()
        try:
            logger.info(
                f"🔄 Фоновый воркер: Старт полной индексации проекта: {project_path.name}"
            )
            _last_index_error = None

            # МУЛЬТИПРОЕКТНОСТЬ: Динамическое переключение БД под конкретную папку
            indexer.switch_project(project_path)

            project_file_guard = FileGuard(project_path)
            indexer.file_guard = project_file_guard

            # 1. ВЕКТОРНАЯ ИНДЕКСАЦИЯ (LanceDB + LM Studio с учетом семафора)
            indexed_count = 0
            try:
                logger.info("📡 Старт векторного сканирования всего проекта...")
                indexed_count = await asyncio.to_thread(
                    indexer.index_project, project_path
                )
                logger.info(f"🔹 Шаг 1 (Векторы) завершен. Фрагментов: {indexed_count}")
            except Exception as emb_err:
                _last_index_error = f"Ошибка векторного индекса (LM Studio?): {emb_err}"
                logger.error(f"⚠️ Сбой на шаге 1: {emb_err}", exc_info=True)

            # 2. СТРУКТУРНЫЙ ПАРСИНГ СИМВОЛОВ (Tree-sitter)
            try:
                if hasattr(symbol_index, "index_project"):
                    logger.info("🌳 Старт структурного парсинга Tree-sitter...")
                    await asyncio.to_thread(
                        symbol_index.index_project, project_path, parser
                    )
                    logger.info("🔹 Шаг 2 (Символы) завершен успешно.")
            except Exception as sym_err:
                logger.error(
                    f"⚠️ Сбой на шаге 2 (Tree-sitter): {sym_err}", exc_info=True
                )
                if not _last_index_error:
                    _last_index_error = f"Ошибка парсера символов: {sym_err}"

            if not _last_index_error:
                logger.info(
                    f"✅ Фоновый воркер: Проект {project_path.name} полностью готов."
                )
            else:
                logger.warning(
                    f"⚠️ Индексация завершена с ошибками: {_last_index_error}"
                )

        except Exception as critical_err:
            _last_index_error = f"Критический сбой цикла воркера: {critical_err}"
            logger.error(
                f"❌ Критическая ошибка внутри воркера: {critical_err}", exc_info=True
            )
        finally:
            _signal_all_events()
            _task_queue.task_done()


def create_mcp_server() -> "FastMCP":
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("MSCodebase Intelligence Server")
    ext_root = Path(__file__).resolve().parent.parent.parent

    # Инициализация ядра
    embedder = RemoteEmbedder(port=1234)
    default_file_guard = FileGuard(ext_root)

    from src.core.indexer import _generate_unique_db_path

    initial_db_path = _generate_unique_db_path(ext_root)
    indexer = Indexer(initial_db_path, embedder, default_file_guard)
    searcher = Searcher(indexer, embedder)
    indexer.searcher = searcher

    # Защита LM Studio от конкурентного спама пачками эмбеддингов
    embedder._lm_studio_semaphore = threading.Semaphore(2)
    original_embed_batch = embedder.embed_batch

    def embed_batch_with_semaphore(texts, is_query=False):
        with embedder._lm_studio_semaphore:
            return original_embed_batch(texts, is_query)

    embedder.embed_batch = embed_batch_with_semaphore

    symbol_index = SymbolIndex()
    code_parser = CodeParser()

    def ensure_worker_started():
        global _task_queue, _worker_task
        if _task_queue is None:
            _task_queue = asyncio.Queue()
            _worker_task = asyncio.create_task(
                background_queue_worker(indexer, symbol_index, code_parser)
            )
            logger.info("⚡ Очередь задач для первичной сборки инициализирована.")

    # ==========================================
    # ИНСТРУМЕНТЫ MCP ДЛЯ AI-АГЕНТА (ZED PROMPT)
    # ==========================================

    @mcp.tool()
    def get_index_status(kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Возвращает текущую статистику заполнения векторной базы данных LanceDB и индекса символов."""
        stats = indexer.get_status()
        if "error" in stats:
            return f"❌ Ошибка получения статуса: {stats['error']}"

        total_symbols = (
            symbol_index.get_symbol_count()
            if hasattr(symbol_index, "get_symbol_count")
            else "N/A"
        )
        embedder_mode = getattr(embedder, "mode", "unknown")
        mode_label = {
            "lm_studio": "🌐 LM Studio",
            "ollama": "🦙 Ollama",
            "onnx": "⚙️ ONNX (локальный)",
            "fallback": "⚠️ Заглушка",
        }.get(embedder_mode, embedder_mode)

        output = (
            f"📊 Статус базы данных MSCodebase:\n"
            f"  • Всего фрагментов кода в базе (LanceDB): {stats.get('total_chunks', 0)}\n"
            f"  • Проиндексировано уникальных файлов: {stats.get('unique_files', 0)}\n"
            f"  • Найдено структурных символов (Tree-sitter): {total_symbols}\n"
            f"  • Состояние движка: {stats.get('status', 'unknown')}\n"
            f"  • Режим эмбеддера: {mode_label}"
        )
        if _last_index_error:
            output += f"\n  ⚠️ Последняя ошибка индексации: {_last_index_error}"
        return output

    @mcp.tool()
    async def index_project_dir(
        path: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> str:
        """Добавляет директорию проекта в фоновую очередь на первичную синхронизацию."""
        global _last_index_error
        _last_index_error = None

        ensure_worker_started()
        target_path = Path(path).resolve()
        if not target_path.exists():
            return f"❌ Указанный путь не существует: {path}"

        await _task_queue.put(target_path)
        return f'{{\n  "status": "success",\n  "message": "Первичная индексация проекта {target_path.name} запущена."\n}}'

    @mcp.tool()
    def search_code(query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Выполняет гибридный семантический поиск по фрагментам исходного кода проекта."""
        return searcher.search(query, limit=6)

    @mcp.tool()
    def get_context(query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Генерирует интеллектуальный упакованный контекст для AI-ассистента в стиле Cursor @codebase."""
        return get_context_func(query, searcher)

    @mcp.tool()
    def get_symbol_info(query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Ищет точные совпадения для определений и использований по их имени."""
        if not symbol_index:
            return "❌ Индекс символов не инициализирован."
        try:
            results = symbol_index.search_symbols(query)
            if not results:
                return f"🔍 Символ '{query}' не найден в структуре определений проекта."

            definitions = []
            usages = []
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

    @mcp.tool()
    def get_repo_map(project_root: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Возвращает текстовую карту репозитория: дерево файлов и ключевые символы."""
        if not symbol_index:
            return "❌ Движок анализа структуры недоступен."
        try:
            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь к проекту не найден: {project_root}"

            if hasattr(symbol_index, "get_repo_map"):
                raw_map = symbol_index.get_repo_map(str(target_path))
                output = [
                    f"🗺️ Карта репозитория проекта: {target_path.name}\n",
                    f"Всего отслеживаемых файлов: {raw_map.get('total_files', 0)}",
                    f"Всего уникальных символов: {raw_map.get('total_symbols', 0)}\n",
                    "📁 Структура и ключевые компоненты:",
                ]

                for item in raw_map.get("structure", []):
                    prefix = "  📄" if item["type"] == "file" else "  📁"
                    output.append(f"{prefix} {item['name']} ({item['path']})")
                    file_path = item["path"]
                    symbols_entry = raw_map.get("symbols_by_file", {}).get(file_path)

                    if symbols_entry is None:
                        file_path_alt = file_path.replace("/", "\\")
                        symbols_entry = raw_map.get("symbols_by_file", {}).get(
                            file_path_alt
                        )

                    if symbols_entry:
                        for sym in symbols_entry:
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
            return f"🗺️ Карта проекта '{target_path.name}' не поддерживается."
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
