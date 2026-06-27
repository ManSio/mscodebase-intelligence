"""
MSCodebase Intelligence MCP Server — Фоновый асинхронный воркер и полный набор из 6 инструментов MCP
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.file_guard import FileGuard
from src.core.indexer import Indexer
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher

# Импорт FastMCP отложен — он выполняется внутри create_mcp_server(),
# когда sys.path уже правильно настроен (src/ удалён из sys.path).
# Это предотвращает shadow-конфликт: src/mcp/ не должен перекрывать site-packages mcp.

# Безопасный импорт движков контекста и символов
try:
    from src.core.context_engine import get_context as get_context_func
    from src.core.parser import CodeParser
    from src.core.symbol_index import SymbolIndex
except ImportError as e:
    logging.getLogger("mscodebase_server.handler").error(
        f"Ошибка импорта локальных модулей: {e}"
    )
    raise

logger = logging.getLogger("mscodebase_server.handler")

_task_queue: Optional[asyncio.Queue] = None
_worker_task: Optional[asyncio.Task] = None
_last_index_error: Optional[str] = None  # Последняя ошибка индексации
_task_events: list = []  # Список asyncio.Event для отслеживания завершения задач


def _signal_all_events():
    """Сигналит всем ожидающим событиям о завершении задачи."""
    events = _task_events[:]  # копия, т.к. список может измениться
    for ev in events:
        ev.set()


async def background_queue_worker(
    indexer: Indexer, symbol_index: SymbolIndex, parser: "CodeParser"
):
    """
    Единственный потребитель задач индексации.
    Последовательно и независимо обновляет как векторный LanceDB индекс, так и структурный SymbolIndex.
    """
    global _last_index_error
    logger.info("⚙️ Асинхронный Queue-воркер запущен и готов к обработке задач.")
    while True:
        project_path = await _task_queue.get()
        try:
            logger.info(
                f"🔄 Фоновый воркер: Старт полной индексации проекта: {project_path.name}"
            )
            _last_index_error = None  # Сбрасываем старую ошибку перед началом работы

            # === МУЛЬТИПРОЕКТНОСТЬ: Динамическое переключение БД ===
            indexer.switch_project(project_path)

            # Создаём FileGuard под конкретный проект (чтобы .gitignore работал правильно)
            project_file_guard = FileGuard(project_path)
            indexer.file_guard = project_file_guard

            # 1. ВЕКТОРНАЯ ИНДЕКСАЦИЯ (LanceDB + LM Studio)
            indexed_count = 0
            try:
                logger.info("📡 Старт векторной индексации (шаг 1)...")
                indexed_count = await asyncio.to_thread(
                    indexer.index_project, project_path
                )
                logger.info(
                    f"🔹 Шаг 1 завершен. Проиндексировано фрагментов: {indexed_count}"
                )
            except Exception as emb_err:
                _last_index_error = f"Ошибка векторного индекса (LM Studio?): {emb_err}"
                logger.error(
                    f"⚠️ Сбой на шаге 1 (векторная индексация): {emb_err}", exc_info=True
                )

            # 2. СТРУКТУРНЫЙ ПАРСИНГ СИМВОЛОВ (Tree-sitter)
            try:
                if hasattr(symbol_index, "index_project"):
                    logger.info("🌳 Старт структурного парсинга Tree-sitter (шаг 2)...")
                    await asyncio.to_thread(
                        symbol_index.index_project, project_path, parser
                    )
                    logger.info("🔹 Шаг 2 завершен успешно.")
            except Exception as sym_err:
                logger.error(
                    f"⚠️ Сбой на шаге 2 (Tree-sitter / Repo Map): {sym_err}",
                    exc_info=True,
                )
                if not _last_index_error:
                    _last_index_error = f"Ошибка парсера символов: {sym_err}"

            if not _last_index_error:
                logger.info(
                    f"✅ Фоновый воркер: Проект {project_path.name} успешно синхронизирован "
                    f"({indexed_count} файлов)."
                )
            else:
                logger.warning(
                    f"⚠️ Индексация завершена частично из-за ошибок. Статус: {_last_index_error}"
                )

        except Exception as critical_err:
            _last_index_error = f"Критический сбой цикла воркера: {critical_err}"
            logger.error(
                f"❌ Критическая ошибка выполнения внутри воркера: {critical_err}",
                exc_info=True,
            )
        finally:
            _signal_all_events()
            _task_queue.task_done()


def create_mcp_server() -> "FastMCP":
    from mcp.server.fastmcp import FastMCP  # Отложенный импорт — см. комментарий выше

    mcp = FastMCP("MSCodebase Intelligence Server")
    ext_root = Path(__file__).resolve().parent.parent.parent

    # Инициализация компонентов ядра
    embedder = RemoteEmbedder(port=1234)
    # FileGuard пересоздаётся в queue_worker под конкретный проект для правильного .gitignore
    default_file_guard = FileGuard(ext_root)

    # Создаём изолированную базу данных для каждого проекта
    # Импортируем функцию здесь, чтобы избежать циклических импортов
    from src.core.indexer import _generate_unique_db_path

    # Для начальной инициализации используем корневую директорию проекта
    # В реальности путь к базе будет переопределен в background_queue_worker
    # для каждого конкретного проекта, который индексируется
    initial_db_path = _generate_unique_db_path(ext_root)
    indexer = Indexer(initial_db_path, embedder, default_file_guard)
    searcher = Searcher(indexer, embedder)
    indexer.searcher = searcher

    # Добавляем семафор для ограничения параллельных запросов к LM Studio
    # Это предотвращает перегрузку LM Studio при параллельной индексации в нескольких окнах
    import threading

    embedder._lm_studio_semaphore = threading.Semaphore(
        2
    )  # Ограничиваем до 2 параллельных запросов

    # Оборачиваем embed_batch методом, который использует семафор
    original_embed_batch = embedder.embed_batch

    def embed_batch_with_semaphore(texts, is_query=False):
        with embedder._lm_studio_semaphore:
            return original_embed_batch(texts, is_query)

    embedder.embed_batch = embed_batch_with_semaphore

    # SymbolIndex — in-memory индекс символов
    symbol_index = SymbolIndex()

    # Настоящий экземпляр CodeParser для Tree-sitter
    code_parser = CodeParser()

    def ensure_worker_started():
        global _task_queue, _worker_task
        if _task_queue is None:
            _task_queue = asyncio.Queue()
            _worker_task = asyncio.create_task(
                background_queue_worker(indexer, symbol_index, code_parser)
            )
            logger.info(
                "⚡ Очередь asyncio.Queue и фоновый Task успешно инициализированы."
            )

    # 1. Инструмент MCP: Статус базы
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

        # Текущий режим эмбеддера (LM Studio / Ollama / ONNX)
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

        # Добавляем последнюю ошибку индексации, если есть
        if _last_index_error:
            output += f"\n  ⚠️ Последняя ошибка индексации: {_last_index_error}"

        return output

    # 2. Инструмент MCP: Добавление проекта в очередь
    @mcp.tool()
    async def index_project_dir(
        path: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> str:
        """Добавляет директорию проекта в фоновую очередь на синхронизацию.

        Возвращает результат сразу после запуска процесса в фоне.
        Индексация выполняется асинхронно, не блокируя интерфейс Zed.
        """
        global _last_index_error
        _last_index_error = None

        ensure_worker_started()
        target_path = Path(path).resolve()
        if not target_path.exists():
            return f"❌ Указанный путь не существует: {path}"

        # Просто добавляем задачу в очередь и возвращаем ответ о запуске
        # Индексация выполняется асинхронно в фоне воркером
        await _task_queue.put(target_path)

        # Возвращаем JSON-ответ о запуске в фоне, не ожидая завершения
        return f'{{\n  "status": "success",\n  "message": "Индексация проекта {target_path.name} успешно запущена в фоновом режиме."\n}}'

    # 3. Инструмент MCP: Семантический поиск кусков кода
    @mcp.tool()
    def search_code(query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Выполняет гибридный семантический поиск по фрагментам исходного кода проекта."""
        return searcher.search(query, limit=6)

    # 4. Инструмент MCP: Cursor @codebase Контекст-движок
    @mcp.tool()
    def get_context(query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Генерирует интеллектуальный упакованный контекст для AI-ассистента в стиле Cursor @codebase."""
        return get_context_func(query, searcher)

    # 5. Инструмент MCP: Точный поиск определений и использований
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
                    # Ищем совпадение ключа с разными разделителями (Windows vs POSIX)
                    symbols_entry = raw_map.get("symbols_by_file", {}).get(file_path)
                    if symbols_entry is None:
                        # Fallback: пробуем с обратным слешем на Windows
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
