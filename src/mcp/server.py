"""MSCodebase Intelligence MCP Server - Чистый набор инструментов без поллинга файловой системы"""

import asyncio
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.file_guard import FileGuard
from src.core.structural_search import StructuralSearcher
from src.core.indexer import Indexer
from src.core.eta_predictor import ETAPredictor
from src.core.execution_contract import ExecutionContract
from src.core.health_report import HealthReport, format_health_report
from src.core.log_manager import setup_project_logging, get_log_summary, get_recent_errors
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher
from src.core.multi_project_searcher import MultiProjectSearcher, ProjectRegistry

try:
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

# Task Queue для фоновых задач (Bug Correlation, Relations, etc.)
from src.core.task_queue import get_task_queue as _get_task_queue
_background_task_queue = _get_task_queue()

# ETA Predictor — предсказание времени выполнения
from src.core.eta_predictor import get_predictor as _get_predictor
from src.core.autonomous_fix import AutonomousFixLoop
_eta_predictor = _get_predictor()


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


# ══════════════════════════════════════════════════════════
# Фоновые задачи для Task Queue
# ══════════════════════════════════════════════════════════

def _run_bug_correlation(memory) -> str:
    """Выполняет анализ баго-корреляции в фоне."""
    from src.core.bug_correlation import BugCorrelation

    bug_corr = BugCorrelation(memory)
    stats = bug_corr.analyze()
    hotspots = bug_corr.get_hotspots(10)

    lines = [
        f"🐛 Bug Correlation Analysis",
        f"",
        f"  Всего коммитов: {stats['total_commits']}",
        f"  Баг-фиксов: {stats['bugfix_commits']} ({stats['bugfix_ratio']:.1%})",
        f"  Уникальных проблемных файлов: {len(bug_corr._file_bug_count)}",
        f"",
        f"  🔥 Топ-10 горячих точек:",
    ]

    for i, hotspot in enumerate(hotspots, 1):
        risk_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(hotspot['risk'], "⚪")
        lines.append(
            f"    {i}. {risk_emoji} {hotspot['file']} "
            f"(багов: {hotspot['bug_count']}, score: {hotspot['bug_score']})"
        )

    return "\n".join(lines)


def _run_build_graph(memory) -> str:
    """Строит граф знаний в фоне."""
    from src.core.relation_extractor import RelationExtractor

    extractor = RelationExtractor(memory)
    relations = extractor.extract_all_relations()
    summary = extractor.get_relation_summary()

    lines = [
        f"🔗 Knowledge Graph Built",
        f"",
        f"  Всего связей: {summary['total_relations']}",
    ]

    if 'by_type' in summary:
        for rel_type, count in summary['by_type'].items():
            lines.append(f"   - {rel_type}: {count}")

    # Топ-10 cochange связей
    cochange = relations.get('cochange', [])
    if cochange:
        lines.append(f"\n  📊 Топ cochange связи:")
        for rel in cochange[:10]:
            lines.append(f"     {rel['source']} ↔ {rel['target']} (weight: {rel['weight']})")

    return "\n".join(lines)


def _run_full_analysis(memory) -> str:
    """Полный анализ: баги + граф знаний."""
    bug_result = _run_bug_correlation(memory)
    graph_result = _run_build_graph(memory)
    return f"{bug_result}\n\n{graph_result}"


_last_progress: Dict[str, Any] = {}
_progress_lock = threading.Lock()


def _cleanup_old_progress():
    """Удаляет записи прогресса старше 1 часа (защита от memory leak)."""
    now = time.time()
    expired = [
        k for k, v in _last_progress.items()
        if now - v.get("timestamp", 0) > 3600
    ]
    for k in expired:
        del _last_progress[k]


def _create_progress_callback(project_name: str):
    """Создаёт callback для отслеживания прогресса индексации.

    Возвращает callable который обновляет внутренний счётчик прогресса
    и логирует каждые 10 файлов.
    Потокобезопасен через _progress_lock.
    """
    def progress_callback(file_name: str, done: int, total: int, phase: str):
        try:
            # Обновляем внутренний счётчик (потокобезопасно)
            progress_info = {
                "project": project_name,
                "phase": phase,
                "files_done": done,
                "files_total": total,
                "current_file": file_name,
                "percent": (done / total * 100) if total > 0 else 0,
                "timestamp": time.time(),
            }
            with _progress_lock:
                _last_progress[project_name] = progress_info

            # Логируем прогресс каждые 10 файлов или на ключевых этапах
            if done % 10 == 0 or phase in ("complete", "rebuilding_bm25", "error_security"):
                logger.info(
                    f"📊 Прогресс индексации [{project_name}]: "
                    f"{done}/{total} ({progress_info['percent']:.0f}%) — {phase}"
                )
        except Exception as e:
            # Ошибка callback не должна прерывать индексацию
            logger.debug(f"Progress callback error (non-critical): {e}")

    return progress_callback


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
                # Создаём progress callback для отслеживания
                progress_cb = _create_progress_callback(project_path.name)
                indexed_count = await asyncio.to_thread(
                    indexer.index_project, project_path, progress_callback=progress_cb
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

                    # Сохраняем SymbolIndex на диск (persistence)
                    try:
                        from src.core.index_guard import IndexGuard
                        guard = IndexGuard(indexer.db_path, project_path)
                        guard.save_symbol_index(symbol_index)
                        logger.info("💾 SymbolIndex сохранён на диск.")
                    except Exception as save_err:
                        logger.warning(f"Не удалось сохранить SymbolIndex: {save_err}")

                    # Обновляем счётчик символов для get_index_status
                    global _total_symbols_count
                    _total_symbols_count = len(symbol_index._definitions)

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

    # Загружаем SymbolIndex из кэша если есть (persistence между перезапусками)
    try:
        from src.core.index_guard import IndexGuard
        guard = IndexGuard(initial_db_path, ext_root)
        if guard.load_symbol_index(symbol_index):
            logger.info(f"📦 SymbolIndex загружен из кэша: {len(symbol_index._definitions)} символов")
    except Exception as e:
        logger.debug(f"SymbolIndex cache не загружен: {e}")

    # Cross-repo поиск: реестр проектов и мультипроектный поисковик
    project_registry = ProjectRegistry()
    project_registry.register(ext_root)
    multi_project_searcher = MultiProjectSearcher(embedder, project_registry)

    # Инициализация файлового логирования для проекта
    setup_project_logging(ext_root)
    logger.info("🚀 MCP-сервер запущен")

    # ==========================================
    # ИНКРЕМЕНТАЛЬНАЯ ИНДЕКСАЦИЯ ЧЕРЕЗ LSP
    # ==========================================
    # LSP-сервер (src/lsp_main.py) получает события didSave от Zed
    # и индексирует файлы напрямую из памяти (без чтения с диска).
    # MCP-сервер только читает базу для поиска.
    # Watdog больше не нужен — LSP делает всю работу!
    logger.info("📦 MCP-сервер работает в режиме read-only (индексация через LSP)")

    def ensure_worker_started():
        global _task_queue, _worker_task
        if _task_queue is None:
            _task_queue = asyncio.Queue()
            _worker_task = asyncio.create_task(
                background_queue_worker(indexer, symbol_index, code_parser)
            )
            logger.info("⚡ Очередь задач для первичной сборки инициализирована.")

        # Запускаем TaskQueue для фоновых задач
        if not _background_task_queue._worker_task:
            asyncio.create_task(_background_task_queue.start())
            logger.info("⚡ TaskQueue для фоновых задач запущена.")

    # ==========================================
    # ИНСТРУМЕНТЫ MCP ДЛЯ AI-АГЕНТА (ZED PROMPT)
    # ==========================================

    @mcp.tool()
    def notify_change(file_path: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Уведомляет об изменении файла (для внешних вызовов, например из LSP).

        Используйте этот инструмент когда хотите принудительно обновить индекс
        конкретного файла без ожидания автоматического watcher.

        ПРИОРИТЕТ ИСТОЧНИКА:
        1. LSP VFS (память) — если файл открыт в Zed, берём актуальный текст из буфера
        2. Диск — fallback если файл не открыт в Zed

        Args:
            file_path: Абсолютный или относительный путь к файлу

        Returns:
            Статус обновления индекса
        """
        _debug_log("notify_change", file_path)
        try:
            path = Path(file_path).resolve()
            if not path.exists():
                return f"❌ Файл не существует: {file_path}"

            try:
                rel_path = str(path.relative_to(ext_root))
            except ValueError:
                return f"❌ Файл вне проекта: {file_path}"

            # Пытаемся получить текст из LSP VFS (актуальная версия из памяти Zed)
            content = None
            try:
                from src.hybrid_server import server as lsp_server
                if lsp_server and hasattr(lsp_server, 'workspace'):
                    uri = f"file:///{str(path).replace(chr(92), '/')}"
                    doc = lsp_server.workspace.get_document(uri)
                    if doc and hasattr(doc, 'source'):
                        content = doc.source
                        logger.info(f"📝 notify_change: взял из LSP VFS ({len(content)} chars)")
            except Exception as e:
                logger.debug(f"notify_change: LSP VFS недоступен, fallback на диск: {e}")

            # Если есть shared_indexer (hybrid mode) — используем его
            try:
                from src.hybrid_server import shared_indexer
                if shared_indexer._initialized:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Мы уже в async контексте — планируем задачу
                        asyncio.ensure_future(
                            shared_indexer.index_file(path, content)
                        )
                    else:
                        loop.run_until_complete(
                            shared_indexer.index_file(path, content)
                        )
                    return f"✅ Обновлено (hybrid): {rel_path}"
            except ImportError:
                pass

            # Fallback: обычный indexer (legacy mode)
            source = "lsp_vfs" if content is not None else "filesystem"
            if indexer._index_single_file(path, rel_path, content=content, source=source):
                return f"✅ Обновлено: {rel_path}"
            return f"⏭️ Без изменений: {rel_path}"
        except Exception as e:
            logger.error(f"Ошибка notify_change: {e}")
            return f"❌ Ошибка: {e}"

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
    def index_health(project_root: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Полная диагностика и самовосстановление индекса.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - get_index_status показывает 0 чанков или 0 символов
        - Поиск возвращает пустые результаты
        - Подозреваешь что индекс повреждён
        - Хочешь проверить здоровье базы данных

        Проверяет:
        - Схему LanceDB (совместимость)
        - Целостность данных
        - SymbolIndex (Tree-sitter)
        - Нужна ли переиндексация

        Автоматически восстанавливает:
        - Несовместимую схему (миграция)
        - Потерянный SymbolIndex (пересоздание из кэша)
        - Пустую таблицу (запуск reindex)
        """
        _debug_log("index_health", project_root)
        try:
            from src.core.index_guard import IndexGuard, quick_health_check

            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь не существует: {project_root}"

            # Находим путь к БД
            normalized_path = str(target_path.resolve()).lower().replace('\\', '/')
            project_hash = __import__('hashlib').md5(normalized_path.encode()).hexdigest()[:8]
            project_name = target_path.name.lower()
            db_path = target_path.parent / ".codebase_indices" / "lancedb_v2" / f"index_{project_name}_{project_hash}.db"

            if not db_path.exists():
                return (
                    f"⚠️ База данных не найдена: {db_path.name}\n"
                    f"   Запустите index_project_dir для создания."
                )

            # Быстрая проверка
            health = quick_health_check(db_path)

            lines = [f"🏥 Index Health Check: {target_path.name}"]
            lines.append("")
            lines.append(f"  Таблица LanceDB: {'✅' if health['table_exists'] else '❌'}")
            lines.append(f"  Чанков: {health['row_count']}")
            lines.append(f"  Схема OK: {'✅' if health['schema_ok'] else '❌'}")
            lines.append(f"  SymbolIndex: {'✅' if health['symbol_index_exists'] else '❌ (будет пересоздан'}")
            lines.append(f"  Общий статус: {'✅ Здоров' if health['healthy'] else '⚠️ Требует внимания'}")

            if health.get("error"):
                lines.append(f"\n  Ошибка: {health['error']}")

            # Если есть проблемы — запускаем полную проверку
            if not health["healthy"]:
                lines.append(f"\n🔧 Запуск самовосстановления...")
                try:
                    import lancedb
                    db = lancedb.connect(str(db_path))
                    guard = IndexGuard(db_path, target_path)
                    report = guard.check_and_repair(db)

                    lines.append(f"  Статус: {report['status']}")
                    if report['actions_taken']:
                        lines.append(f"  Действия: {', '.join(report['actions_taken'])}")
                    if report['errors']:
                        lines.append(f"  Ошибки: {', '.join(report['errors'])}")

                    if report['status'] == 'needs_reindex':
                        lines.append(f"\n  ⚠️ Требуется переиндексация!")
                        lines.append(f"  Вызовите: index_project_dir('{project_root}')")
                except Exception as e:
                    lines.append(f"  ❌ Ошибка восстановления: {e}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Ошибка index_health: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def get_index_progress(kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Возвращает текущий прогресс индексации для всех проектов.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Хочешь понять сколько осталось до завершения индексации
        - Нужно решить подождать или уже можно искать
        - Индексация запущена но статус неизвестен

        Возвращает форматированный статус по каждому проекту.
        """
        _debug_log("get_index_progress")

        # Очистка старых записей (потокобезопасно)
        _cleanup_old_progress()

        with _progress_lock:
            progress_copy = _last_progress.copy()

        if not progress_copy:
            return "📊 Индексация не запущена. Используйте index_project_dir для начала."

        lines = ["📊 Прогресс индексации:"]
        for project, info in progress_copy.items():
            status_emoji = "✅" if info["phase"] == "complete" else "🔄"
            lines.append(
                f"  {status_emoji} {project}: "
                f"{info['files_done']}/{info['files_total']} "
                f"({info['percent']:.0f}%) — {info['phase']}"
            )
            if info["phase"] == "complete":
                lines.append(f"     ✅ Индексация завершена, можно искать!")
            elif info["percent"] > 0:
                remaining = info["files_total"] - info["files_done"]
                lines.append(f"     ⏳ Осталось ~{remaining} файлов")

        return "\n".join(lines)

    @mcp.tool()
    async def index_project_dir(
        path: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> str:
        """Добавляет директорию проекта в фоновую очередь на первичную синхронизацию.

        CRITICAL USAGE RULES:
        1. Use native Windows paths (backslashes) — do NOT normalize to POSIX.
        2. After calling this, ALWAYS call get_index_status() to verify cache state.
        3. Используй get_index_progress() для отслеживания прогресса.
        4. Watcher автоматически обнаружит изменения через 2-3 секунды.
        """
        _debug_log("index_project_dir", path)
        global _last_index_error
        _last_index_error = None

        ensure_worker_started()
        target_path = Path(path).resolve()
        if not target_path.exists():
            return f"❌ Указанный путь не существует: {path}"

        await _task_queue.put(target_path)

        # Регистрируем проект в реестре для cross-repo поиска
        project_registry.register(target_path)

        return f'{{\n  "status": "success",\n  "message": "Первичная индексация проекта {target_path.name} запущена."\n}}'

    @mcp.tool()
    def search_code(query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """CRITICAL MANDATORY TOOL — CALL THIS FIRST FOR ALL CODE QUERIES.

        ⚠️ NEVER use grep or find_path for conceptual/semantic queries.
        This tool uses AST-based semantic search with 81% token compression.
        It is mathematically impossible for native grep to provide this level
        of context quality. Using this tool reduces LLM thinking time by 4x.

        ✅ USE THIS FIRST FOR:
        - Any question about code, architecture, logic, or bugs
        - Finding implementations by meaning (not exact text)
        - Understanding dependencies between modules
        - Before writing/editing any code that integrates with existing code

        ❌ DO NOT USE FOR:
        - Reading a SPECIFIC known file → use read_file
        - Exact text match in known location → use grep as fallback only

        The 1-2s latency is INVESTED TIME that saves 3-5x more during generation.
        """
        _debug_log("search_code", query)

        if not query or not query.strip():
            return "❌ Пустой поисковый запрос. Укажите что искать."

        try:
            # Определяем режим: agentic или обычный
            use_agentic = False
            if kwargs and kwargs.get("agentic") in (True, "true", "1", 1):
                use_agentic = True
            elif kwargs and kwargs.get("mode") == "agentic":
                use_agentic = True
            else:
                # Автоматическое определение: сложный запрос = agentic
                # Если запрос содержит "и", "а", "также", "как", "где", "что" и длинный
                import re
                complexity_indicators = [
                    r"\bи\b", r"\bа\b", r"\bтакже\b", r"\bплюс\b",
                    r"\bкак\b", r"\bгде\b", r"\bчто\b", r"\bкогда\b",
                    r",\s+",  # запятая с пробелом
                ]
                indicators_count = sum(
                    1 for pattern in complexity_indicators
                    if re.search(pattern, query.lower())
                )
                # Если 2+ индикатора или запрос > 50 символов — agentic
                use_agentic = indicators_count >= 2 or len(query) > 50

            if use_agentic:
                return _agentic_search_handler(query, symbol_index)
            else:
                return searcher.search(query, limit=6)
        except Exception as e:
            logger.error(f"Ошибка search_code: {e}", exc_info=True)
            return (
                f"❌ Ошибка при выполнении поиска: {type(e).__name__}: {e}\n"
                f"Попробуйте переформулировать запрос или проверьте логи через get_logs()."
            )

    def _agentic_search_handler(query: str, symbol_index) -> str:
        """Обработчик Agentic Code Search для search_code."""
        try:
            results, metadata = searcher.agentic_code_search(
                query,
                symbol_index=symbol_index,
                max_subqueries=4,
                limit_per_subquery=5,
                max_total_results=10,
            )

            if not results:
                return "🔍 По запросу ничего не найдено (база пуста или эмбеддер недоступен)."

            output_lines = [
                f"🧠 Agentic Code Search: найдено {len(results)} результатов\n"
            ]

            # Показываем декомпозицию
            if metadata.get("subqueries") and len(metadata["subqueries"]) > 1:
                output_lines.append("📝 Декомпозиция запроса:")
                for i, sq in enumerate(metadata["subqueries"], 1):
                    count = metadata["subquery_results_count"].get(sq[:40], 0)
                    output_lines.append(f"   {i}. {sq} ({count} результатов)")
                output_lines.append("")

            # Показываем связи между результатами
            relations = metadata.get("relations")
            if relations:
                if relations.get("common_files"):
                    output_lines.append(
                        f"🔗 Пересекающиеся файлы: {', '.join(relations['common_files'][:5])}"
                    )
                if relations.get("flow_description"):
                    output_lines.append(f"📊 {relations['flow_description']}")
                if relations.get("coverage_score", 0) > 0:
                    pct = int(relations["coverage_score"] * 100)
                    output_lines.append(f"📈 Покрытие: {pct}%")
                output_lines.append("")

            # Результаты
            for i, res in enumerate(results, 1):
                score = res.get("final_score", 0.0)
                output_lines.append(
                    f"{i}. 📄 {res['metadata']['file']} [Чанк #{res['metadata']['chunk_index']}] "
                    f"(score={score:.4f})\n"
                    f"```\n{res['text']}\n```\n"
                    f"{'-' * 60}\n"
                )

            return "".join(output_lines)
        except Exception as e:
            logger.error(f"Ошибка agentic_code_search: {e}", exc_info=True)
            # Fallback на обычный поиск
            return searcher.search(query, limit=6)

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
    def impact_analysis(symbol: str, depth: int = 3, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Анализ влияния изменения/удаления символа на весь проект.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно понять, что сломается при изменении функции/класса
        - Оценить риск рефакторинга перед внесением изменений
        - Найти все зависимости символа (прямые и косвенные)
        - Определить scope изменений для code review

        Args:
            symbol: Имя символа (функция, класс, метод)
            depth: Глубина анализа графа (1-5, по умолчанию 3)

        Returns:
            Структурированный отчёт с метриками риска:
            - direct_callers: сколько напрямую вызывает этот символ
            - transitive_callers: косвенные зависимости
            - affected_files: файлы, которые нужно проверить
            - risk_level: low | medium | high | critical
            - risk_score: 0-100
        """
        _debug_log("impact_analysis", f"{symbol}, depth={depth}")
        if not symbol_index:
            return "❌ Движок анализа структуры недоступен."
        try:
            result = symbol_index.get_impact_analysis(symbol, depth=depth)

            if not result.get("call_graph", {}).get("definition"):
                return f"⚠️ Символ '{symbol}' не найден в индексе."

            output = [
                f"🎯 Impact Analysis: {symbol}",
                f"",
                f"📊 Метрики влияния:",
                f"  • Прямые вызывающие: {result['direct_callers']}",
                f"  • Косвенные вызывающие: {result['transitive_callers']}",
                f"  • Прямые зависимости: {result['direct_callees']}",
                f"  • Косвенные зависимости: {result['transitive_callees']}",
                f"",
                f"⚠️ Риск: {result['risk_level'].upper()} (score: {result['risk_score']}/100)",
                f"",
                f"📁 Затронутые файлы ({len(result['affected_files'])}):",
            ]
            for f in result["affected_files"][:15]:
                output.append(f"  • {f}")
            if len(result["affected_files"]) > 15:
                output.append(f"  ... и ещё {len(result['affected_files']) - 15}")

            if result["affected_modules"]:
                output.append(f"")
                output.append(f"📦 Затронутые модули: {', '.join(result['affected_modules'])}")

            return "\n".join(output)
        except Exception as e:
            logger.error(f"Ошибка при работе инструмента impact_analysis: {e}")
            return f"❌ Ошибка анализа влияния: {str(e)}"

    @mcp.tool()
    def find_similar_bugs(error_message: str, project_root: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Находит похожие баги из истории проекта.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Получил ошибку и хочешь знать как решали раньше
        - Ищешь похожие проблемы в истории коммитов
        - Хочешь понять паттерны багов в проекте

        Args:
            error_message: Описание ошибки или исключения
            project_root: Путь к проекту

        Returns:
            Список похожих баг-фиксов из истории
        """
        _debug_log("find_similar_bugs", f"{error_message[:50]}, {project_root}")
        try:
            from src.core.commit_memory import CommitMemory

            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь не существует: {project_root}"

            memory = CommitMemory(target_path)
            similar = memory.find_similar_bugs(error_message, max_results=5)

            if not similar:
                return f"⚠️ Похожие баги не найдены для: {error_message[:50]}"

            output = [
                f"🔍 Similar Bugs Found: {len(similar)}",
                f"",
                f"  Query: {error_message[:60]}",
                f"",
            ]

            for i, bug in enumerate(similar, 1):
                output.append(f"  {i}. [{bug['hash']}] {bug['date'][:10]}")
                output.append(f"     {bug['message'][:70]}")
                output.append(f"     Relevance: {bug['relevance_score']}")
                if bug['files']:
                    output.append(f"     Files: {', '.join(bug['files'][:3])}")
                output.append("")

            return "\n".join(output)

        except Exception as e:
            logger.error(f"Ошибка find_similar_bugs: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def get_hotspots(project_root: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Находит 'горячие точки' — файлы с высоким баго-рейтом.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Хочешь знать какие файлы чаще всего ломаются
        - Планируешь рефакторинг
        - Оцениваешь риски изменения

        Args:
            project_root: Путь к проекту

        Returns:
            Список файлов с метриками риска
        """
        _debug_log("get_hotspots", project_root)
        try:
            from src.core.commit_memory import CommitMemory

            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь не существует: {project_root}"

            memory = CommitMemory(target_path)
            hotspots = memory.get_hotspots(min_changes=3)

            if not hotspots:
                return "⚠️ Горячие точки не найдены"

            output = [
                f"🔥 Hotspots (files with high bug rate):",
                f"",
            ]

            for i, h in enumerate(hotspots[:10], 1):
                risk_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(h["risk"], "⚪")
                output.append(
                    f"  {i}. {risk_emoji} {h['file']}"
                )
                output.append(
                    f"     Changes: {h['total_changes']}, "
                    f"Bugfixes: {h['bugfix_changes']}, "
                    f"Bug ratio: {h['bug_ratio']:.0%}"
                )

            return "\n".join(output)

        except Exception as e:
            logger.error(f"Ошибка get_hotspots: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def get_repo_map(project_root: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Возвращает RepoRank — рейтинг важности символов проекта.

        Использует алгоритм PageRank на графе вызовов:
        - Символы с высоким rank — "сердце" проекта
        - Используются чаще всего и критически важны

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно понять какие функции/классы самые важные
        - Определить приоритеты для рефакторинга
        - Найти "центральные" модули проекта

        Args:
            project_root: Путь к проекту
            top_k: Количество топ-символов (по умолчанию 20)

        Returns:
            Список символов с RepoRank score (0-1)
        """
        _debug_log("get_repo_rank", f"{project_root}, top_k={top_k}")
        if not symbol_index:
            return "❌ Движок анализа структуры недоступен."
        try:
            ranks = symbol_index.compute_repo_rank()
            if not ranks:
                return "⚠️ Граф вызовов пуст. Нет данных для RepoRank."

            # Сортируем по score
            sorted_ranks = sorted(ranks.items(), key=lambda x: x[1], reverse=True)[:top_k]

            output = [f"🏆 RepoRank: Top-{len(sorted_ranks)} символов\n"]
            for i, (symbol, score) in enumerate(sorted_ranks, 1):
                # Получаем информацию о символе
                defs = symbol_index.find_definitions(symbol)
                kind = defs[0].kind if defs else "unknown"
                file = defs[0].file_path if defs else "unknown"
                output.append(f"  {i}. [{score:.3f}] {symbol} ({kind}) — {file}")

            return "\n".join(output)
        except Exception as e:
            logger.error(f"Ошибка get_repo_rank: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def get_branch_info(project_root: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Информация о текущей git-ветке и индексе.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно узнать текущую ветку и состояние индекса
        - Проверить что индекс соответствует ветке
        - Список всех индексов для веток

        Returns:
            Информация о ветке, пути к БД, количестве чанков
        """
        _debug_log("get_branch_info", project_root)
        try:
            from src.core.branch_aware_index import BranchAwareIndex

            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь не существует: {project_root}"

            branch_index = BranchAwareIndex(target_path)
            info = branch_index.get_branch_info()

            output = [
                f"🌿 Branch Info:",
                f"  • Текущая ветка: {info['branch']}",
                f"  • Путь к БД: {info['db_path']}",
                f"  • Индекс существует: {'✅' if info['index_exists'] else '❌'}",
                f"  • Чанков в индексе: {info['total_chunks']}",
            ]

            # Список всех индексов
            all_indices = branch_index.list_branch_indices()
            if all_indices:
                output.append(f"")
                output.append(f"📁 Все индексы веток:")
                for branch, chunks in all_indices.items():
                    output.append(f"  • {branch}: {chunks} чанков")

            return "\n".join(output)
        except Exception as e:
            logger.error(f"Ошибка get_branch_info: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def get_commit_history(project_root: str, limit: int = 10, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Возвращает семантическую историю изменений проекта.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно понять историю изменений файла или символа
        - Найти какие файлы обычно меняются вместе
        - Определить стабильность модуля

        Args:
            project_root: Путь к проекту
            limit: Количество последних коммитов

        Returns:
            История коммитов с метаданными
        """
        _debug_log("get_commit_history", f"{project_root}, limit={limit}")
        try:
            from src.core.commit_memory import CommitMemory

            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь не существует: {project_root}"

            memory = CommitMemory(target_path)
            commits = memory.fetch_commits(limit=limit)

            if not commits:
                return "⚠️ Нет коммитов или git недоступен."

            output = [f"📜 Commit History (последние {len(commits)}):\n"]

            for i, commit in enumerate(commits[:limit], 1):
                hash_short = commit["hash"][:8]
                date = commit.get("date", "")[:10]
                msg = commit.get("message", "")[:60]
                files = len(commit.get("files", []))
                output.append(f"  {i}. [{hash_short}] {date} — {msg}")
                output.append(f"     Файлов изменено: {files}")

            # Статистика
            stats = memory.get_stats()
            output.append(f"")
            output.append(f"� Статистика:")
            output.append(f"  • Всего коммитов: {stats['total']}")
            if stats.get("authors"):
                for author, count in stats["authors"].items():
                    output.append(f"  • {author}: {count} коммитов")

            return "\n".join(output)
        except Exception as e:
            logger.error(f"Ошибка get_commit_history: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def get_file_history(project_root: str, file_path: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Возвращает историю изменений конкретного файла.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно понять эволюцию файла
        - Найти кто и когда менял файл
        - Определить стабильность модуля

        Args:
            project_root: Путь к проекту
            file_path: Относительный путь к файлу

        Returns:
            История изменений файла
        """
        _debug_log("get_file_history", f"{project_root}, {file_path}")
        try:
            from src.core.commit_memory import CommitMemory

            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь не существует: {project_root}"

            memory = CommitMemory(target_path)

            # Получаем коммиты для файла
            commits = memory.get_commits_for_file(file_path)
            stability = memory.get_file_stability(file_path)

            if not commits:
                return f"⚠️ Нет коммитов для файла: {file_path}"

            output = [
                f"� File History: {file_path}",
                f"� Стабильность: {stability['stability']}",
                f"� Количество изменений: {stability['change_count']}",
                f"",
                f"Последние коммиты:\n",
            ]

            for i, commit in enumerate(commits[:10], 1):
                hash_short = commit["hash"][:8]
                date = commit.get("date", "")[:10]
                msg = commit.get("message", "")[:60]
                output.append(f"  {i}. [{hash_short}] {date} — {msg}")

            return "\n".join(output)
        except Exception as e:
            logger.error(f"Ошибка get_file_history: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def get_bug_correlation(project_root: str, file_path: str = "", kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Анализ связи багов с изменениями в коде (Bug Correlation).

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно понять какие модули чаще всего ломаются
        - Определить "горячие точки" проекта
        - Найти файлы с высокой баго-нагрузкой
        - Оценить риск изменения файла

        Args:
            project_root: Путь к проекту
            file_path: Путь к файлу (опционально — если нужен анализ конкретного файла)

        Returns:
            Отчёт по баго-корреляции
        """
        _debug_log("get_bug_correlation", f"{project_root}, {file_path}")
        try:
            from src.core.commit_memory import CommitMemory
            from src.core.bug_correlation import BugCorrelation

            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь не существует: {project_root}"

            memory = CommitMemory(target_path)
            bug_corr = BugCorrelation(memory)

            if file_path:
                # Детальный анализ конкретного файла
                history = bug_corr.get_bug_history_for_file(file_path)

                output = [
                    f"🐛 Bug History: {file_path}",
                    f"",
                    f"  Риски: {history['bug_risk'].upper()}",
                    f"  Баг-коммитов: {history['bug_count']}/{history['total_commits']}",
                    f"  Баго-доля: {history['bug_ratio']:.1%}",
                    f"",
                ]

                if history['bug_commits']:
                    output.append("  Последние баг-фиксы:")
                    for i, commit in enumerate(history['bug_commits'][:5], 1):
                        hash_short = commit["hash"][:8]
                        date = commit.get("date", "")[:10]
                        msg = commit.get("message", "")[:50]
                        output.append(f"    {i}. [{hash_short}] {date} — {msg}")

                return "\n".join(output)
            else:
                # Общий анализ по проекту
                stats = bug_corr.analyze()
                hotspots = bug_corr.get_hotspots(10)

                output = [
                    f"🐛 Bug Correlation Analysis",
                    f"",
                    f"  Всего коммитов: {stats['total_commits']}",
                    f"  Баг-фиксов: {stats['bugfix_commits']} ({stats['bugfix_ratio']:.1%})",
                    f"  Уникальных проблемных файлов: {len(bug_corr._file_bug_count)}",
                    f"",
                    f"  🔥 Топ-10 горячих точек:",
                ]

                for i, hotspot in enumerate(hotspots, 1):
                    risk_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(hotspot['risk'], "⚪")
                    output.append(
                        f"    {i}. {risk_emoji} {hotspot['file']} "
                        f"(багов: {hotspot['bug_count']}, score: {hotspot['bug_score']})"
                    )

                return "\n".join(output)

        except Exception as e:
            logger.error(f"Ошибка get_bug_correlation: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def get_related_files(project_root: str, file_path: str, max_depth: int = 1, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Находит файлы связанные с данным (Knowledge Graph).

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно понять какие файлы затронет изменение
        - Ищете ""родственные"" модули
        - Хотите оценить каскадный эффект рефакторинга

        Типы связей:
        - cochange: файлы меняющиеся вместе
        - bug_correlation: связанные через баг-фиксы
        - call: вызовы между символами

        Args:
            project_root: Путь к проекту
            file_path: Целевой файл
            max_depth: Глубина поиска (1 или 2)

        Returns:
            Список связанных файлов
        """
        _debug_log("get_related_files", f"{project_root}, {file_path}, depth={max_depth}")
        try:
            from src.core.commit_memory import CommitMemory
            from src.core.relation_extractor import RelationExtractor

            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь не существует: {project_root}"

            memory = CommitMemory(target_path)
            extractor = RelationExtractor(memory)

            # Строим граф знаний
            extractor.extract_all_relations()
            related = extractor.get_related_files(file_path, max_depth=max_depth)

            if not related:
                return f"⚠️ Связанные файлы не найдены для: {file_path}"

            output = [
                f"🔗 Related Files: {file_path}",
                f"  Глубина поиска: {max_depth}",
                f"  Найдено связей: {len(related)}",
                f"",
            ]

            for i, rel in enumerate(related[:15], 1):
                path_str = " → ".join(rel['path'])
                output.append(
                    f"  {i}. [{rel['depth']}] {rel['file']} "
                    f"(weight: {rel['total_weight']:.1f})"
                )
                if rel['depth'] > 1:
                    output.append(f"     Путь: {path_str}")

            # Добавляем сводку по типам связей
            summary = extractor.get_relation_summary()
            output.extend([
                f"",
                f"  📊 Граф знаков:",
                f"     Всего связей: {summary['total_relations']}",
            ])
            if 'by_type' in summary:
                for rel_type, count in summary['by_type'].items():
                    output.append(f"     - {rel_type}: {count}")

            return "\n".join(output)

        except Exception as e:
            logger.error(f"Ошибка get_related_files: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def submit_background_task(task_type: str, project_root: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Запускает долгую задачу в фоне.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно проанализировать баги по всему проекту
        - Построить граф знаний
        - Выполнить тяжёлые вычисления без таймаута

        Доступные типы задач:
        - 'bug_correlation' — анализ баго-нагрузки
        - 'build_knowledge_graph' — построение графа знаний
        - 'full_analysis' — полный анализ (баги + связи)

        Args:
            task_type: Тип задачи
            project_root: Путь к проекту

        Returns:
            task_id для отслеживания прогресса
        """
        _debug_log("submit_background_task", f"{task_type}, {project_root}")
        try:
            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь не существует: {project_root}"

            from src.core.commit_memory import CommitMemory
            from src.core.bug_correlation import BugCorrelation
            from src.core.relation_extractor import RelationExtractor

            memory = CommitMemory(target_path)

            if task_type == "bug_correlation":
                task_id = _background_task_queue.submit_sync(
                    "Bug Correlation Analysis",
                    _run_bug_correlation,
                    memory,
                )
            elif task_type == "build_knowledge_graph":
                task_id = _background_task_queue.submit_sync(
                    "Build Knowledge Graph",
                    _run_build_graph,
                    memory,
                )
            elif task_type == "full_analysis":
                task_id = _background_task_queue.submit_sync(
                    "Full Analysis",
                    _run_full_analysis,
                    memory,
                )
            else:
                return f"❌ Неизвестный тип задачи: {task_type}"

            # Предсказываем ETA
            eta = _eta_predictor.estimate(task_type)
            eta_str = _eta_predictor.format_eta(eta)

            return (
                f"✅ Задача поставлена в очередь\n"
                f"   ID: {task_id}\n"
                f"   Тип: {task_type}\n"
                f"   ETA: {eta_str}\n"
                f"   Проверьте: get_task_status('{task_id}')"
            )

        except Exception as e:
            logger.error(f"Ошибка submit_background_task: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def get_task_status(task_id: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Возвращает статус фоновой задачи.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно проверить завершилась ли фоновая задача
        - Получить результат долгого анализа
        - Отследить прогресс

        Args:
            task_id: ID задачи (из submit_background_task)

        Returns:
            Статус задачи и результат если завершена
        """
        _debug_log("get_task_status", task_id)
        status = _background_task_queue.get_status(task_id)
        if not status:
            return f"❌ Задача не найдена: {task_id}"

        lines = [
            f"📋 Задача: {status['name']}",
            f"   ID: {status['id']}",
            f"   Статус: {status['status']}",
            f"   Прогресс: {status['progress']*100:.0f}%",
            f"   Создана: {status['created_at']}",
        ]

        if status['started_at']:
            lines.append(f"   Начата: {status['started_at']}")
        if status['completed_at']:
            lines.append(f"   Завершена: {status['completed_at']}")

        if status['status'] == 'completed':
            lines.append(f"\n✅ Результат:")
            result = status['result']
            if isinstance(result, str):
                lines.append(result)
            elif isinstance(result, dict):
                for k, v in result.items():
                    lines.append(f"   {k}: {v}")
        elif status['status'] == 'failed':
            lines.append(f"\n❌ Ошибка: {status['error']}")
        elif status['status'] == 'running':
            # Показываем примерное время оставшееся
            progress = status['progress']
            if progress > 0.05:
                elapsed = (datetime.now() - datetime.fromisoformat(status['started_at'])).total_seconds()
                estimated_total = elapsed / progress
                remaining = estimated_total * (1 - progress)
                lines.append(f"\n🔄 Выполняется... (~{remaining:.0f}с осталось)")
            else:
                lines.append(f"\n🔄 Выполняется...")
        elif status['status'] == 'queued':
            lines.append(f"\n⏳ В очереди...")

        return "\n".join(lines)

    @mcp.tool()
    def predict_eta(operation: str, items: int = 1, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Предсказывает время выполнения операции (ETA).

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно понять сколько займёт операция
        - Планируешь массовый анализ
        - Хочешь оценить стоимость в токенах

        Доступные операции:
        - 'search' — гибридный поиск
        - 'index_file' — индексация одного файла
        - 'index_project' — индексация всего проекта
        - 'bug_correlation' — анализ баго-нагрузки
        - 'knowledge_graph' — построение графа знаний
        - 'impact_analysis' — анализ влияния изменения
        - 'file_history' — история файла
        - 'commit_analysis' — анализ коммитов

        Args:
            operation: Тип операции
            items: Количество элементов (файлов, запросов)

        Returns:
            Предсказание времени и стоимости
        """
        _debug_log("predict_eta", f"{operation}, items={items}")
        try:
            est = _eta_predictor.estimate(operation, items)
            eta_str = _eta_predictor.format_eta(est)

            lines = [
                f"⏱️ ETA Prediction: {est['operation']}",
                f"",
                f"   Операция: {operation}",
                f"   Количество: {items}",
                f"   Время: {eta_str}",
                f"   Токенов: ~{est['tokens_estimate']}",
                f"   Уверенность: {est['confidence']}",
            ]

            # Примерная стоимость
            tokens = est['tokens_estimate']
            cost_gpt4 = (tokens / 1000) * 0.01
            lines.append(f"   Стоимость (GPT-4): ~${cost_gpt4:.4f}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Ошибка predict_eta: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def run_health_check(kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Полная проверка здоровья проекта.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно проверить что проект в порядке
        - После изменений кода
        - Для диагностики проблем

        Проверяет:
        - Тесты (pytest)
        - Git status
        - Общее состояние

        Returns:
            Отчет о здоровье проекта
        """
        _debug_log("run_health_check")
        try:
            from src.core.autonomous_fix import AutonomousFixLoop

            ext_root = Path(__file__).resolve().parent.parent.parent
            fix_loop = AutonomousFixLoop(ext_root)
            health = fix_loop.health_check()

            lines = [
                f"🏥 Project Health Check",
                f"",
                f"   Время: {health['timestamp'][:19]}",
            ]

            # Tests
            tests = health.get("tests", {})
            if tests:
                status_emoji = "✅" if tests.get("success") else "❌"
                lines.append(f"   Тесты: {status_emoji} {tests.get('passed', 0)} passed, {tests.get('failed', 0)} failed")

            # Git
            git = health.get("git_status", {})
            if git:
                if git.get("dirty"):
                    lines.append(f"   Git: ⚠️ {len(git.get('dirty_files', []))} uncommitted files")
                else:
                    lines.append(f"   Git: ✅ clean")

            # Overall
            overall = health.get("overall", "unknown")
            overall_emoji = "✅" if overall == "healthy" else "❌"
            lines.append(f"")
            lines.append(f"   Итого: {overall_emoji} {overall}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Ошибка health_check: {e}")
            return f"❌ Ошибка: {str(e)}"

    @mcp.tool()
    def smart_search(query: str, mode: str = "quality", limit: int = 5, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Умный поиск с выбором режима (FAST/QUALITY/DEEP).

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужен быстрый поиск (fast, ~300ms)
        - Нужен качественный поиск с reranker (quality, ~1200ms)
        - Нужен глубокий анализ (deep, ~2-5s)

        Режимы:
        - 'fast' — embedding + vector search, ~300ms
        - 'quality' — + LLM reranker, ~1200ms
        - 'deep' — + graph analysis, ~2-5s

        Args:
            query: Поисковый запрос
            mode: Режим (fast/quality/deep)
            limit: Максимум результатов

        Returns:
            Результаты поиска с метриками
        """
        _debug_log("smart_search", f"{mode}, {query[:30]}")
        try:
            searcher = _get_searcher()
            if not searcher:
                return "❌ Поисковый движок недоступен. Запустите index_project_dir."

            result = searcher.search_with_mode(query, mode=mode, limit=limit)
            results = result["results"]
            timing = result["timing_ms"]

            if not results:
                return f"🔍 По запросу '{query}' ничего не найдено."

            # Форматируем результат
            mode_emoji = {"fast": "⚡", "quality": "🎯", "deep": "🔬"}
            lines = [
                f"{mode_emoji.get(mode, '🔍')} Smart Search [{mode.upper()}]",
                f"",
                f"   Query: {query}",
                f"   Results: {len(results)}",
                f"   Time: {timing.get('total_ms', 0):.0f}ms",
            ]

            if result.get("cache_hit"):
                lines.append(f"   Cache: HIT ✅")

            if "embed_ms" in timing:
                lines.append(f"   Embed: {timing['embed_ms']:.0f}ms")
            if "search_ms" in timing:
                lines.append(f"   Search: {timing['search_ms']:.0f}ms")

            lines.append("")

            for i, res in enumerate(results[:limit], 1):
                code_text = res.get("text_full") or res["text"]
                score = res.get("final_score", res.get("score", 0))
                lines.append(
                    f"{i}. 📄 {res['metadata']['file']} "
                    f"[Chunk #{res['metadata']['chunk_index']}] "
                    f"(score: {score:.3f})"
                )
                lines.append(f"```\n{code_text[:300]}\n```")
                lines.append("-" * 40)

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Ошибка smart_search: {e}")
            return f"❌ Ошибка: {str(e)}"

    def _get_searcher():
        """Получает или создаёт searcher."""
        global _last_searcher
        if "_last_searcher" not in globals() or _last_searcher is None:
            try:
                ext_root = Path(__file__).resolve().parent.parent.parent
                from src.core.indexer import Indexer, _generate_unique_db_path
                from src.core.remote_embedder import RemoteEmbedder
                from src.core.file_guard import FileGuard

                embedder = RemoteEmbedder(port=1234)
                file_guard = FileGuard(ext_root)
                db_path = _generate_unique_db_path(ext_root)
                indexer = Indexer(db_path, embedder, file_guard, project_path=ext_root)
                _last_searcher = Searcher(indexer, embedder)
            except Exception as e:
                logger.error(f"Не удалось создать searcher: {e}")
                return None
        return _last_searcher

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

        АВТОЗАГРУЗКА МОДЕЛЕЙ:
        При вызове автоматически проверяет какие модели загружены в VRAM.
        Если критические модели (embedding/instruct) не загружены — отправляет
        тестовый запрос для загрузки «по требованию».
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

        # ══════════════════════════════════════════════════════════
        # Проверка загруженных моделей в LM Studio + автозагрузка
        # ══════════════════════════════════════════════════════════
        if embedder_mode in ("lm_studio", "ollama"):
            try:
                import httpx
                host = getattr(embedder, "host", "127.0.0.1")
                port = getattr(embedder, "port", 1234)

                # Запрашиваем список моделей с их состоянием
                with httpx.Client(timeout=3.0) as client:
                    r = client.get(f"http://{host}:{port}/api/v0/models")
                    if r.status_code == 200:
                        models = r.json().get("data", [])
                        loaded = [m for m in models if m.get("state") == "loaded"]
                        not_loaded = [m for m in models if m.get("state") != "loaded"]

                        lines.append("")
                        lines.append(f"📦 Модели LM Studio: {len(loaded)}/{len(models)} в VRAM")

                        if loaded:
                            for m in loaded:
                                mtype = m.get("type", "?")
                                lines.append(f"   ✅ [{mtype}] {m.get('id', '')}")

                        if not_loaded:
                            for m in not_loaded:
                                mtype = m.get("type", "?")
                                lines.append(f"   ⚪ [{mtype}] {m.get('id', '')}")

                        # Автозагрузка: если ни одна embedding-модель не в VRAM
                        embedding_loaded = any(
                            m.get("type") == "embeddings" for m in loaded
                        )
                        instruct_loaded = any(
                            m.get("type") in ("llm", "vlm") for m in loaded
                        )

                        if not embedding_loaded or not instruct_loaded:
                            lines.append("")
                            lines.append("🔄 Автозагрузка моделей...")

                            # Загружаем embedding-модель
                            if not embedding_loaded:
                                embed_model = getattr(embedder, "model_name", "text-embedding-bge-m3")
                                try:
                                    r_load = client.post(
                                        f"http://{host}:{port}/v1/embeddings",
                                        json={"model": embed_model, "input": "warmup"},
                                        timeout=60.0,
                                    )
                                    if r_load.status_code == 200:
                                        lines.append(f"   ✅ Embedding '{embed_model}' загружена")
                                    else:
                                        lines.append(f"   ⚠️ Embedding '{embed_model}': HTTP {r_load.status_code}")
                                except Exception as e:
                                    lines.append(f"   ❌ Embedding '{embed_model}': {e}")

                            # Загружаем instruct-модель (для реранкинга)
                            if not instruct_loaded:
                                # Ищем первую instruct-модель в списке доступных
                                instruct_candidates = [
                                    m for m in not_loaded
                                    if m.get("type") in ("llm", "vlm")
                                ]
                                if instruct_candidates:
                                    instruct_model = instruct_candidates[0].get("id")
                                    try:
                                        r_inst = client.post(
                                            f"http://{host}:{port}/v1/chat/completions",
                                            json={
                                                "model": instruct_model,
                                                "messages": [{"role": "user", "content": "hi"}],
                                                "max_tokens": 1,
                                            },
                                            timeout=120.0,
                                        )
                                        if r_inst.status_code == 200:
                                            lines.append(f"   ✅ Instruct '{instruct_model}' загружена")
                                        else:
                                            lines.append(f"   ⚠️ Instruct '{instruct_model}': HTTP {r_inst.status_code}")
                                    except Exception as e:
                                        lines.append(f"   ❌ Instruct '{instruct_model}': {e}")
                    else:
                        lines.append(f"  • Модели LM Studio: ⚠️ HTTP {r.status_code}")
            except Exception as e:
                lines.append(f"  • Модели LM Studio: ❌ Ошибка: {e}")

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
        try:
            return searcher.context_search(selected_code, limit=5)
        except Exception as e:
            logger.error(f"Ошибка context_search: {e}", exc_info=True)
            return f"❌ Ошибка поиска по коду: {type(e).__name__}: {e}"

    @mcp.tool()
    def structural_search(
        project_root: str,
        pattern: str = "class_inheritance",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Поиск по AST-паттернам (Structural Search).

        Ищет код не по тексту, а по структуре через Tree-sitter queries.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно найти все классы наследующие от Base
        - Нужно найти все функции с декоратором @app.get
        - Нужно найти все async def, with statement, comprehensions
        - Нужна структура кода, а не текстовый поиск

        ДОСТУПНЫЕ ПАТТЕРНЫ:
        - class_inheritance — классы с наследованием
        - class_with_decorator — классы с декораторами
        - function_with_decorator — функции с декораторами
        - async_function — async функции
        - method_with_type_hints — методы с аннотациями типов
        - class_with_init — классы с __init__
        - import_from — импорты from X import Y
        - try_except — try/except блоки
        - list_comprehension — list comprehensions
        - dict_comprehension — dict comprehensions
        - lambda — лямбда-функции
        - with_statement — with statements
        - comprehension — любые comprehensions
        """
        _debug_log("structural_search", f"{project_root} | {pattern}")
        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return f"Указанный путь не существует: {project_root}"

        try:
            searcher = StructuralSearcher(code_parser)
            result = searcher.search(
                target_path,
                pattern_name=pattern,
                max_results=30,
            )
            return searcher.format_results(result)
        except Exception as e:
            logger.error(f"Ошибка structural_search: {e}")
            return f"Ошибка структурного поиска: {str(e)}"

    @mcp.tool()
    def deep_search(query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Итеративный глубокий поиск с уточнением запроса (Agentic Deep Search).

        Выполняет несколько итераций поиска, анализируя результаты и уточняя запрос
        на основе ключевых терминов из найденных фрагментов.

        CRITICAL: This tool provides the highest-quality context for complex queries.
        It invests 2-4 seconds in multi-step research to deliver a concentrated,
        noise-free context that saves significant tokens during LLM generation.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Запрос сложный и требует глубокого понимания кодовой базы
        - Обычный поиск дал мало результатов
        - Нужно найти связанные реализации через несколько шагов
        - Задача требует исследования, а не простого поиска

        НЕ ИСПОЛЬЗУЙ КОГДА:
        - Запрос простой и конкретный -> используй search_code
        - Нужно найти конкретный символ -> используй get_symbol_info
        - Нужен поиск по структуре AST -> используй structural_search

        CRITICAL: If get_index_status() reported empty (0 chunks), this tool will return
        empty results. Fall back to grep/find_path instead.
        """
        _debug_log("deep_search", query)
        try:
            return searcher.deep_search(query, limit=8)
        except Exception as e:
            logger.error(f"Ошибка deep_search: {e}", exc_info=True)
            return f"❌ Ошибка глубокого поиска: {type(e).__name__}: {e}"

    @mcp.tool()
    def cross_repo_search(query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Поиск по нескольким проектам с @-mention синтаксисом (Cross-repo Search).

        Ищет по всем проиндексированным проектам или только по указанным через @-mentions.
        Результаты из разных проектов объединяются через RRF (Reciprocal Rank Fusion).

        СИНТАКСИС:
        - "query" — поиск по всем проектам
        - "query @backend" — поиск только в проекте backend
        - "query @backend @frontend" — поиск в backend и frontend
        - "query @shared" — поиск по префиксу (найдёт shared-utils, shared-types и т.д.)

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно найти код в другом проекте моно-репо
        - Нужно понять как интерфейс используется в разных сервисах
        - Нужно найти общие типы/утилиты в shared-библиотеках
        - Обычный search_code ищет только в текущем проекте

        НЕ ИСПОЛЬЗУЙ КОГДА:
        - Нужен поиск в одном проекте -> используй search_code
        - Нужен поиск по структуре AST -> используй structural_search

        CRITICAL: All projects must be indexed first via index_project_dir.
        """
        _debug_log("cross_repo_search", query)
        try:
            return multi_project_searcher.search(query, limit=8)
        except Exception as e:
            logger.error(f"Ошибка cross_repo_search: {e}", exc_info=True)
            return f"❌ Ошибка кросс-проектного поиска: {type(e).__name__}: {e}"

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

    @mcp.tool()
    def get_health_report(project_root: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Самодиагностика системы — проверяет здоровье индекса, логов, синхронизации.

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - Нужно проверить общее состояние системы
        - Поиск возвращает странные результаты
        - Подозреваешь что индекс рассинхронизирован с диском
        - Хочешь увидеть все ошибки и предупреждения в одном отчёте

        Возвращает:
            - overall_health: healthy / warning / critical
            - metrics: количество чанков, файлов, символов, ошибок
            - issues: критические проблемы
            - warnings: предупреждения
        """
        _debug_log("get_health_report", project_root)
        try:
            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return f"❌ Путь не существует: {project_root}"

            report = HealthReport(
                project_path=target_path,
                indexer=indexer if 'indexer' in dir() else None,
                symbol_index=symbol_index if 'symbol_index' in dir() else None,
                embedder=embedder if 'embedder' in dir() else None,
            )
            result = report.run_full_diagnostic()
            return format_health_report(result)
        except Exception as e:
            logger.error(f"Ошибка get_health_report: {e}")
            return f"❌ Ошибка диагностики: {str(e)}"

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

## 1. MCP PRIORITY RULES (Mandatory Tool Hierarchy)
- **CRITICAL:** For ANY question about code, architecture, logic, or bugs — call `search_code` FIRST.
  Only if it returns no results or fails, fall back to `grep`/`find_path`.
  The 1-2s latency is invested time that saves 3-5x more during LLM generation.
- IF `get_index_status` returns chunks = 0 or status = "empty":
  - Call `index_project_dir(path)` to trigger re-indexing, then wait for completion.
  - Use `grep` as fallback ONLY while indexing is in progress.
- IF chunks > 0:
  - For semantic/conceptual questions → `search_code` (ALWAYS FIRST).
  - For exact symbol names → `get_symbol_info`.
  - For exact text in known location → `grep` (fallback only).

## 2. RECONNAISSANCE BEFORE ACTION (No Blind Reads/Writes)
- NEVER guess line numbers. Calling `read_file` with speculative ranges (e.g., 1-100 on a random file) is a Critical Failure.
- BEFORE reading or modifying any file, you MUST discover the exact location using `get_symbol_info` or text search.
- Once the line numbers are known from tool output, you may proceed to read.
- To find similar code patterns or duplicates, use `context_search(selected_code)` — it embeds the selected code and finds semantically similar chunks.
- For complex research queries, use `deep_search(query)` — it performs iterative search with query refinement across multiple passes.
- For cross-project search in mono-repos, use `cross_repo_search(query @project1 @project2)` — searches across multiple indexed projects.
- **Agentic Code Search (search_code agentic=True):** For complex questions like "how does X work and where is Y?", `search_code` auto-decomposes the query into sub-queries, searches each independently, analyzes relations (common files, symbols), and aggregates via RRF. This is the DEFAULT mode for complex queries.

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

## 6. PATH PROTOCOL
- Use native Windows paths (backslashes) when passing to MCP tools.
- Do NOT normalize to POSIX lowercase — our tools handle Windows paths natively.
- Example: `D:\\Project\\MSCodeBase\\src\\core\\indexer.py`

## 7. POST-MODIFICATION SYNC
- After writing any file, immediately call `index_project_dir(path)` to force re-indexing.
- Call `get_index_status()` to verify that the cache matches the updated state.
- Use `get_index_progress()` to check indexing progress before searching.

## 8. INDEXING PROGRESS AWARENESS
- After `index_project_dir()`, indexing runs asynchronously in background.
- Use `get_index_progress()` to check current status (files done/total, phase).
- IF phase = "complete" → safe to use `search_code` and other search tools.
- IF phase = "scanning" or "rebuilding_bm25" → wait or use grep as fallback.
- IF percent < 50% → warn user that indexing is still in progress.
- IF percent >= 80% → indexing almost done, results may be partial but usable.

## 8. STACK & CONSTRAINTS
- Backend: Python 3.11+, LanceDB (vector search), Tree-sitter (AST parsing).
- Embeddings: LM Studio (external) or fallback to local ONNX.
- Time: IANA timezone via `zoneinfo` (NO pytz).
- Windows native deployment only. NO Docker.
- NEVER mock or stub functions.
    """

    return mcp

    @mcp.tool()
    def verify_action(action_type: str, **kwargs) -> str:
        """Верификация выполненного действия (Execution Contract).

        ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
        - После git commit/push — подтвердить что изменения реально записаны
        - После записи файла — подтвердить что файл существует и содержит ожидаемое
        - После индексации — подтвердить статус через get_index_status

        Args:
            action_type: 'file_write' | 'git_commit' | 'git_push' | 'index_sync'
            **kwargs: параметры для верификации (file_path, expected_content, commit_message)

        Returns:
            Отчёт о верификации с статусом ✅ или ❌.
        """
        _debug_log("verify_action", action_type)
        try:
            contract = ExecutionContract()
            results = []

            if action_type == "file_write":
                file_path = kwargs.get("file_path", "")
                expected = kwargs.get("expected_content")
                result = contract.verify_file_write(file_path, expected)
                results.append(result)

            elif action_type == "git_commit":
                expected_msg = kwargs.get("expected_message")
                result = contract.verify_git_commit(expected_msg)
                results.append(result)

            elif action_type == "git_push":
                result = contract.verify_git_push()
                results.append(result)

            elif action_type == "index_sync":
                project_root = kwargs.get("project_root", "")
                result = contract.verify_index_sync(project_root)
                results.append(result)

            elif action_type == "all":
                # Полная верификация после commit+push
                file_path = kwargs.get("file_path")
                if file_path:
                    results.append(contract.verify_file_write(file_path))
                results.append(contract.verify_git_commit())
                results.append(contract.verify_git_push())

            else:
                return f"❌ Неизвестный тип действия: {action_type}"

            return format_verification_report(results)

        except Exception as e:
            logger.error(f"Ошибка verify_action: {e}")
            return f"❌ Ошибка верификации: {str(e)}"


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
