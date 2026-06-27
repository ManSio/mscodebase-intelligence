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
from src.core.log_manager import setup_project_logging, get_log_summary, get_recent_errors
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


def _debug_log(tool_name: str, detail: str = ""):
    """Маркерная запись для проверки живости MCP-сервера."""
    import datetime

    try:
        log_path = Path(__file__).resolve().parent.parent.parent / "mcp_debug.log"
        with open(log_path, "a", encoding="utf-8") as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] MCP tool called: {tool_name} | {detail[:80]}\n")
    except Exception:
        pass


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

            # Переключаем логирование на новый проект
            setup_project_logging(project_path)
            logger.info(f"🔄 Переключение на проект: {project_path.name}")

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
    code_parser = CodeParser()
    indexer = Indexer(initial_db_path, embedder, default_file_guard, project_path=ext_root, parser=code_parser)
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

    # Инициализация файлового логирования для проекта
    setup_project_logging(ext_root)
    logger.info("🚀 MCP-сервер запущен")

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
        """Возвращает текущую статистику заполнения векторной базы данных LanceDB и индекса символов.

        CRITICAL USAGE RULE:
        If this tool returns status 'empty' (0 chunks), you MUST immediately fall back to
        grep/find_path tools. Do NOT attempt semantic vector searches on empty index.
        """
        _debug_log("get_index_status")
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
        """Добавляет директорию проекта в фоновую очередь на первичную синхронизацию.

        CRITICAL USAGE RULES:
        1. Normalize Windows paths to POSIX lowercase before calling: path.as_posix().lower()
        2. After calling this, ALWAYS call get_index_status() to verify cache state.
        """
        _debug_log("index_project_dir", path)
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
        """Концептуальный и семантический поиск по смыслу, а не по буквам.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Запрос абстрактный: 'как работает авторизация', 'где обработка ошибок сети'
        - Нужно найти код по смыслу, даже если точных слов в коде нет
        - grep не нашёл результатов потому что термины отличаются

        НЕ ИСПОЛЬЗУЙ КОГДА:
        - Нужно найти конкретный файл по пути -> используй find_path
        - Нужно точное совпадение имени класса -> используй grep

        CRITICAL: If get_index_status() reported empty (0 chunks), this tool will return
        empty results. Fall back to grep/find_path instead.
        """
        _debug_log("search_code", query)
        return searcher.search(query, limit=6)

    @mcp.tool()
    def get_context(query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Генерирует интеллектуальный упакованный контекст для AI-ассистента в стиле Cursor @codebase.

        В отличие от search_code, возвращает сжатый контекст с несколькими фрагментами,
        оптимизированный под токены. Идеален для быстрого погружения в незнакомый код.

        CRITICAL USAGE RULE:
        Only use this tool for targeted context retrieval (specific query).
        DO NOT use it to read entire files — use grep + targeted read_file instead.
        """
        _debug_log("get_context", query)
        return get_context_func(query, searcher)

    @mcp.tool()
    def get_symbol_info(query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Граф вызовов (Call Graph) для символа: определение + кто вызывает + что вызывает сам символ.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно переписать функцию и понять, что из-за этого сломается
        - Нужно найти все места, где вызывается данный метод/класс
        - Нужно понять зависимости между модулями проекта

        Возвращает:
        - definition: где определён символ (файл, строка, тип)
        - callers: кто вызывает этот символ (прямые и косвенные зависимости)
        - callees: какие символы вызывает сам этот символ
        - impact_files: список файлов, которые затронет изменение символа

        CRITICAL USAGE RULE (MANDATORY):
        You MUST call this tool BEFORE using read_file to inspect implementation details.
        This prevents blind reading and ensures you understand the impact scope first.
        """
        _debug_log("get_symbol_info", query)
        if not symbol_index:
            return "❌ Индекс символов не инициализирован."
        try:
            # Сначала пробуем Call Graph (новая логика)
            call_graph = symbol_index.build_call_graph(query, depth=2)

            if (
                call_graph["definition"]
                or call_graph["callers"]
                or call_graph["callees"]
            ):
                output = [f"🗂️ Call Graph для символа '{query}':\n"]

                if call_graph["definition"]:
                    output.append("📍 Определение:")
                    for d in call_graph["definition"]:
                        output.append(
                            f"  • [{d['kind'].upper()}] {d['file']}:{d['line']}"
                        )

                if call_graph["callers"]:
                    output.append("\n📞 Кто вызывает (прямые и косвенные зависимости):")
                    for c in call_graph["callers"][:15]:
                        kind_label = (
                            "(косвенный)" if c.get("kind") == "indirect_caller" else ""
                        )
                        sym_name = c.get("symbol", query)
                        output.append(
                            f"  • {sym_name} в {c['file']}:{c['line']} {kind_label}"
                        )

                if call_graph["callees"]:
                    output.append("\n📤 Что вызывает этот символ:")
                    for c in call_graph["callees"][:10]:
                        output.append(
                            f"  • {c['symbol']} [{c['kind'].upper()}] в {c['file']}:{c['line']}"
                        )

                if call_graph["impact_files"]:
                    output.append(
                        f"\n⚠️ Файлы, затронутые изменением '{query}': {', '.join(call_graph['impact_files'][:10])}"
                    )

                return "\n".join(output)

            # Fallback: старый поиск по имени
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
        """Возвращает текстовую карту репозитория: дерево файлов и ключевые символы.

        CRITICAL USAGE RULE:
        Use this tool for project overview ONLY. To read actual code, use grep + targeted
        read_file (max 50 lines per chunk). Never attempt to parse the full map as code.
        """
        _debug_log("get_repo_map", project_root)
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

    # 7. Инструмент MCP: Архитектурный дифф при сканировании изменений
    @mcp.tool()
    async def scan_changes(
        project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> str:
        """Сканирует проект на изменения и возвращает архитектурный дифф.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Создали/удалили файлы вне Zed (git pull, git checkout)
        - Подозреваешь рассинхронизацию базы с диском
        - Нужно понять влияние изменений на архитектуру проекта

        В отличие от простого 'список изменённых файлов', показывает:
        - Какие символы добавлены/изменены
        - Кто зависит от этих символов (impact analysis)
        - Текстовое резюме архитектурного влияния

        CRITICAL: Normalize Windows paths: path.as_posix().lower() before calling.
        """
        _debug_log("scan_changes", project_root)
        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return f"❌ Указанный путь не существует: {project_root}"

        try:
            indexer.switch_project(target_path)
            project_file_guard = FileGuard(target_path)
            indexer.file_guard = project_file_guard

            # Тяжёлая дисковая операция - в пуле потоков
            logger.info(
                f"🔄 Ручной запуск сканирования изменений для {target_path.name}..."
            )
            indexed_count = await asyncio.to_thread(indexer.index_project, target_path)

            # Обновляем SymbolIndex
            if hasattr(symbol_index, "index_project"):
                await asyncio.to_thread(
                    symbol_index.index_project, target_path, code_parser
                )

            # Архитектурный дифф: какие символы затронуты
            arch_diff = ""
            if hasattr(symbol_index, "get_architectural_diff") and indexed_count > 0:
                # Получаем список файлов, которые были обновлены
                try:
                    df = indexer.table.to_pandas()
                    changed_files = list(df["file_path"].unique())[:20]
                    diff_result = symbol_index.get_architectural_diff(changed_files)
                    if diff_result.get("impact_summary"):
                        arch_diff = f"\n\n🏗️ Архитектурный анализ изменений:\n{diff_result['impact_summary']}"
                    if diff_result.get("impact_files"):
                        arch_diff += f"\n\n⚠️ Файлы под ударом: {', '.join(diff_result['impact_files'][:8])}"
                except Exception as diff_err:
                    logger.debug(f"Не удалось построить архитектурный дифф: {diff_err}")

            embedder_mode = getattr(embedder, "mode", "unknown")
            return (
                f"🔍 Инкрементальное сканирование: {target_path.name}\n"
                f"  • Обновлено/добавлено файлов: {indexed_count}\n"
                f"  • Режим эмбеддера: {embedder_mode}"
                f"{arch_diff}"
            )
        except Exception as e:
            logger.error(f"Ошибка scan_changes: {e}", exc_info=True)
            return f"❌ Ошибка сканирования: {str(e)}"

    # 8. Инструмент MCP: Статус компонентов архитектуры
    @mcp.tool()
    def watcher_status(kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Возвращает статус доступности компонентов подсистем индексации и эмбеддинга.

        CRITICAL USAGE RULE:
        Call this tool to check system health. If embedder mode is 'fallback' or 'onnx',
        notify the user that LM Studio is not connected for full functionality.
        """
        _debug_log("watcher_status")
        lines = ["👁️ Статус компонентов архитектуры:"]

        # Проверка доступности кода LSP в контексте текущего окружения
        try:
            from src.lsp_main import server as lsp_server

            if lsp_server is not None:
                lines.append(
                    "  • Архитектура LSP: ✅ Модули успешно загружены в ядро расширения"
                )
            else:
                lines.append(
                    "  • Архитектура LSP: ⏹️ Ошибка инициализации объекта сервера"
                )
        except Exception as lsp_err:
            lines.append(f"  • Архитектура LSP: ⏹️ Ошибка импорта: {lsp_err}")

        # Режим работы эмбеддера
        embedder_mode = getattr(embedder, "mode", "unknown")
        mode_label = {
            "lm_studio": "🌐 LM Studio (Внешний порт 1234)",
            "ollama": "🦙 Ollama API",
            "onnx": "⚙️ ONNX (Локальный CPU/GPU)",
            "fallback": "⚠️ Fallback-заглушка (Тестовый режим)",
        }.get(embedder_mode, embedder_mode)
        lines.append(f"  • Режим эмбеддера: {mode_label}")

        # Активность фонового потока проверки доступности провайдера
        scanner_thread = getattr(embedder, "_scanner_thread", None)
        scanner_alive = scanner_thread is not None and scanner_thread.is_alive()
        lines.append(
            f"  • Пинг-сканер доступности ИИ-хоста: {'✅ Активен' if scanner_alive else '⏹️ Отключен'}"
        )

        return "\n".join(lines)

    @mcp.tool()
    def context_search(selected_code: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Поиск похожего кода по выделенному фрагменту (Context Search).

        Эмбеддит выделенный код и ищет семантически похожие фрагменты в базе.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно найти дубликаты или похожие реализации
        - Хочешь увидеть альтернативные подходы к решению задачи
        - Нужно найти все места, где используется похожий паттерн

        НЕ ИСПОЛЬЗУЙ КОГДА:
        - Нужно найти конкретный символ -> используй get_symbol_info
        - Нужен семантический поиск по описанию -> используй search_code

        CRITICAL: If get_index_status() reported empty (0 chunks), this tool will return
        empty results. Fall back to grep/find_path instead.
        """
        _debug_log("context_search", selected_code[:80])
        return searcher.context_search(selected_code, limit=5)

    @mcp.tool()
    def get_logs(project_root: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Возвращает последние ошибки и предупреждения из логов проекта.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Что-то работает неправильно и нужно понять причину
        - Индексация зависла или вернула 0 чанков
        - Поиск не даёт результатов — возможно эмбеддер упал
        - Нужно быстро диагностировать проблему без чтения файлов вручную

        Логи хранятся в .codebase_indices/logs/<project>.log с ротацией по 2MB.
        Автоочистка логов старше 7 дней.
        Читает только хвост файла (64KB) — не грузит систему.
        """
        _debug_log("get_logs", project_root)
        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return f"❌ Указанный путь не существует: {project_root}"
        return get_log_summary(target_path)

    # ==========================================
    # MCP PROMPTS — СИСТЕМНЫЕ ПРАВИЛА ДЛЯ AI-АГЕНТА
    # ==========================================

    @mcp.prompt(
        name="mscodebase-rules",
        description="Системные правила для идеальной работы с кодовой базой MSCodeBase",
    )
    def mscodebase_rules() -> str:
        """Системные правила для идеальной работы с кодовой базой MSCodeBase."""
        return """
# MSCODEBASE INTELLIGENCE CORE SYSTEM RULES

You operate under a strict deterministic execution matrix. Every action must be verified before execution. No assumptions allowed.

## 1. STATE-AWARENESS RULES (Database Index Status)
- IF `get_index_status` returns chunks = 0 or status = "empty":
  - You are FORBIDDEN from using `search_code` (semantic vector search).
  - You MUST immediately switch to `grep` or regex-based text search tools.
- IF `get_index_status` returns chunks > 0:
  - For semantic, conceptual, or broad questions ("how does X work?"), use `search_code`.
  - For exact variable names, function definitions, or specific files, use `get_symbol_info` or regex search.

## 2. RECONNAISSANCE BEFORE ACTION (No Blind Reads/Writes)
- NEVER guess line numbers. Calling `read_file` with speculative ranges (e.g., 1-100 on a random file) is a Critical Failure.
- BEFORE reading or modifying any file, you MUST discover the exact location using `get_symbol_info` or text search.
- Once the line numbers are known from tool output, you may proceed to read.
- To find similar code patterns or duplicates, use `context_search(selected_code)` — it embeds the selected code and finds semantically similar chunks.

## 3. CONTEXT BUDGET AND CHUNKING (Anti-Bloat Rules)
- Your maximum allowed reading window is 50 lines per `read_file` call.
- If a function spans more than 50 lines, read the first 50 lines, analyze them, and then make a subsequent targeted call for the next chunk if strictly necessary.
- NEVER ingest entire files into the conversation context unless the file is under 50 lines total.

## 4. SAFE WRITING AND CODE MODIFICATION
- BEFORE generating a search-and-replace block or modifying code, you MUST read the target lines again to ensure your local memory matches the absolute truth of the file.
- When writing code, preserve the exact indentation, style, and architectural patterns of the surrounding file.

## 5. ERROR HANDLING AND FAIL-SAFES
- IF an MCP tool returns an error or empty result:
  - Do not retry the exact same tool with the exact same parameters.
  - Pivot to an alternative tool (e.g., if symbol search failed, try raw text grep).
  - If all technical tools fail, report the exact error signature to the user and ask for clarification.
  - Use `get_logs` to check project logs for embedder failures, indexing errors, or dimension mismatches.

## 6. WINDOWS PATH NORMALIZATION
- Always normalize paths to POSIX lowercase before passing to tools: `path.as_posix().lower()`

## 7. POST-MODIFICATION SYNC
- After writing any file, immediately call `index_project_dir(path)` to force re-indexing.
- Call `get_index_status()` to verify that the cache matches the updated state.

## 8. STACK & CONSTRAINTS
- Backend: Python 3.11+, FastAPI (DI via `Depends`).
- Database: SQLAlchemy Async + SQLite (Alembic migrations only).
- Time: IANA timezone from `.env` via standard `zoneinfo` (NO pytz).
- Windows native deployment only. NO Docker.
- NEVER mock or stub functions.
    """

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
