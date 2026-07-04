"""MSCodebase Intelligence MCP Server — рефакторинг v3

Чистый IoC-ориентированный сервер с DI-контейнером.

Архитектура:
- create_mcp_server() — только регистрация инструментов
- DI Container (ServiceCollection) — единственное место создания зависимостей
- tool/*.py — каждый инструмент в отдельном классе с constructor injection
- core/* — чистая бизнес-логика без MCP-зависимостей
"""

import asyncio
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("mscodebase_server")

# ══════════════════════════════════════════════════════════
# Progress Tracking — для визуализации хода индексации
# ══════════════════════════════════════════════════════════

_last_progress: Dict[str, Any] = {}
_progress_lock = threading.Lock()


def _create_progress_callback(project_name: str):
    """Создаёт callback для отслеживания прогресса индексации.

    Возвращает callable который обновляет внутренний счётчик прогресса
    и логирует каждые 10 файлов. Потокобезопасен через _progress_lock.
    """
    def progress_callback(file_name: str, done: int, total: int, phase: str):
        try:
            now = time.time()
            with _progress_lock:
                existing = _last_progress.get(project_name, {})
                if "started_at" not in existing or existing.get("phase") == "complete":
                    started_at = now
                else:
                    started_at = existing["started_at"]

            progress_info = {
                "project": project_name,
                "phase": phase,
                "files_done": done,
                "files_total": total,
                "current_file": file_name,
                "percent": (done / total * 100) if total > 0 else 0,
                "timestamp": now,
                "started_at": started_at,
            }
            with _progress_lock:
                _last_progress[project_name] = progress_info

            if done % 10 == 0 or phase in ("complete", "rebuilding_bm25", "error_security"):
                logger.info(
                    f"📊 Progress [{project_name}]: "
                    f"{done}/{total} ({progress_info['percent']:.0f}%) — {phase}"
                )
        except Exception:
            pass

    return progress_callback


def _cleanup_old_progress():
    """Удаляет записи прогресса старше 1 часа (защита от memory leak)."""
    now = time.time()
    expired = [
        k for k, v in _last_progress.items() if now - v.get("timestamp", 0) > 3600
    ]
    for k in expired:
        del _last_progress[k]

# ══════════════════════════════════════════════════════════
# Резолвер корня проекта (стабильная логика, не в DI)
# ══════════════════════════════════════════════════════════

_ext_root = Path(__file__).resolve().parent.parent.parent
# Маркер «само-индексация»: project_root указывает на директорию
# самого расширения. Детектим по наличию src/lsp_main.py.
_SELF_INDEX_MARKER = "src" + os.sep + "lsp_main.py"
# Lazy-кэш для env-резолва. ВАЖНО: PROJECT_PATH резолвится на каждый
# вызов resolve_project_root() (см. INC-53EC / REFC-02) — иначе при
# переключении workspace в Zed без рестарта MCP используется stale-путь.
_env_project_root_cache: Optional[Path] = None
_env_cache_lock = threading.Lock()


def _resolve_env_project_root() -> Optional[Path]:
    """Резолвит PROJECT_PATH из окружения лениво + один раз кэширует результат.

    Возвращает None, если PROJECT_PATH не задан / невалиден / указывает
    на сам ext (тогда bridge/ZED_WORKTREE_ROOT/CWD получают шанс).
    """
    global _env_project_root_cache
    with _env_cache_lock:
        if _env_project_root_cache is not None:
            return _env_project_root_cache
        raw = os.environ.get("PROJECT_PATH", "").strip()
        if not raw:
            return None
        # Случай 1: Zed literal "$ZED_WORKTREE_ROOT" без подстановки.
        if raw.startswith("$"):
            zed_root = os.environ.get("ZED_WORKTREE_ROOT")
            if zed_root:
                p = Path(zed_root).resolve()
                if p.exists() and p != _ext_root and (p / _SELF_INDEX_MARKER).exists() is False:
                    _env_project_root_cache = p
                    return _env_project_root_cache
            return None
        # Случай 2: прямой путь.
        try:
            resolved = Path(raw).resolve()
        except (OSError, ValueError):
            return None
        if not resolved.exists() or not resolved.is_dir():
            return None
        # Self-indexing guard (см. INC-53EC / REFC-02): если PROJECT_PATH
        # указывает на ext_root, это почти всегда ошибка пользователя.
        if resolved == _ext_root or (resolved / _SELF_INDEX_MARKER).exists():
            logger.warning(
                f"PROJECT_PATH указывает на само расширение ({resolved}). "
                f"Игнорирую — установите PROJECT_PATH=$ZED_WORKTREE_ROOT."
            )
            return None
        _env_project_root_cache = resolved
        return _env_project_root_cache


def reset_project_root_cache() -> None:
    """Сбрасывает кэш resolve_project_root (для тестов и hot-reload)."""
    global _env_project_root_cache
    with _env_cache_lock:
        _env_project_root_cache = None


def resolve_project_root(provided: str = "") -> Path:
    """Возвращает корень проекта для MCP-инструментов.

    Приоритет (каждый вызов резолвит заново — см. INC-53EC / REFC-02):
    1. Явно переданный provided
    2. LSP→MCP bridge (temp-файл от LSP)
    3. PROJECT_PATH из окружения (lazy, с self-indexing guard)
    4. ZED_WORKTREE_ROOT env
    5. CWD, если != ext_root
    6. ext_root как fallback
    """
    if provided and provided.strip():
        return Path(provided).resolve()

    # LSP→MCP bridge (Windows compat)
    try:
        from src.core.lsp_project_bridge import read_project_from_bridge
        bridge_path = read_project_from_bridge()
        if bridge_path is not None:
            logger.debug(f"resolve_project_root: bridge={bridge_path}")
            return bridge_path
    except Exception:
        pass

    env_root = _resolve_env_project_root()
    if env_root is not None:
        logger.debug(f"resolve_project_root: PROJECT_PATH={env_root}")
        return env_root

    zed_root = os.environ.get("ZED_WORKTREE_ROOT")
    if zed_root:
        zed_path = Path(zed_root).resolve()
        if zed_path.exists() and zed_path != _ext_root:
            logger.debug(f"resolve_project_root: ZED_WORKTREE_ROOT={zed_path}")
            return zed_path

    cwd = Path.cwd().resolve()
    if cwd != _ext_root and (cwd / _SELF_INDEX_MARKER).exists() is False:
        logger.debug(f"resolve_project_root: CWD={cwd}")
        return cwd

    logger.warning(
        f"resolve_project_root: fallback to ext_root={_ext_root} "
        f"(возможна self-indexing; установите PROJECT_PATH=$ZED_WORKTREE_ROOT)"
    )
    return _ext_root


# ══════════════════════════════════════════════════════════
# Создание MCP-сервера
# ══════════════════════════════════════════════════════════

def create_mcp_server() -> "FastMCP":
    """Создаёт и настраивает MCP-сервер с DI-контейнером.

    Шаги:
    1. Создаём FastMCP
    2. Определяем project_root
    3. Создаём DI-контейнер (все зависимости в одном месте)
    4. Регистрируем инструменты (36 шт)
    5. Регистрируем системный prompt
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("MSCodebase Intelligence Server")

    # ─── 1. Project root (default) ────────────────────
    # Используется как fallback если инструмент не передал project_root.
    # Multi-window (INC-6BCB): per-project indexer резолвится в самом
    # инструменте через resolve_indexer_for_request().
    project_root = resolve_project_root()
    logger.info(
        f"🏠 Default project root: {project_root} "
        f"(CWD={Path.cwd().resolve()}, "
        f"PROJECT_PATH={os.environ.get('PROJECT_PATH', 'не установлен')}). "
        f"Per-project indexers via ProjectIndexerRegistry."
    )

    # ─── 2. DI Container (multi-project) ─────────────
    from src.core.di_container import create_service_collection
    services = create_service_collection(project_root)

    # Настройка файлового логирования — в _ext_root с явным label "mcp_global".
    # Per-project логи живут в <project>/.codebase_indices/logs/ через
    # Indexer.notification_broker.
    from src.core.log_manager import setup_project_logging
    try:
        setup_project_logging(_ext_root, project_label="mcp_global")
    except Exception as e:
        logger.debug(f"setup_project_logging fallback: {e}")
    logger.info("🚀 MCP-сервер запущен (DI Container ready, multi-window)")

    # ─── 3. Heartbeat (Anti-Orphan) ─────────────────
    _init_heartbeat()

    # ─── 4. Регистрация инструментов ─────────────────
    _register_all_tools(mcp, services)

    # ─── 4. Системный prompt ─────────────────────────
    _register_system_prompt(mcp)

    # ─── 5. Привязка NotificationBroker к сессии ─────
    # Ждём нотификацию initialized от клиента (Zed), после чего
    # сессия JSON-RPC становится доступна через request_context
    _register_notification_broker(mcp, services)

    # ─── 7. Регистрация JSON-RPC методов для Rust-расширения ─
    _register_extension_handlers(mcp, services)

    # ─── 8. Heartbeat хендлер + фоновый мониторинг ──
    _start_heartbeat_monitor(mcp)

    # ─── 9. Авто-индексация при пустом индексе ───────
    _trigger_auto_index_if_empty(services)

    # ─── 10. Фоновая «дозвонка» до LSP bridge ───────
    # Если resolve_project_root упал в fallback на ext_root (race с LSP),
    # через 1.5s попробуем ещё раз прочитать bridge. Если нашли — обновим
    # кэш env и залогируем. Полная переиндексация НЕ запускается автоматически
    # — пользователь должен вызвать index_project_dir().
    # см. INC-6BCB / multi-window race.
    try:
        from src.core.lsp_project_bridge import read_project_from_bridge
        import threading

        def _delayed_bridge_recheck():
            try:
                time.sleep(1.5)
                bridged = read_project_from_bridge(max_wait=2.0)
                if bridged is not None and bridged.resolve() != _ext_root.resolve():
                    # Сбрасываем кэш resolve_project_root — следующий вызов
                    # выберет bridge как приоритет.
                    reset_project_root_cache()
                    logger.info(
                        f"🌉 Delayed bridge recheck: project_root = {bridged} "
                        f"(LSP дозвонился)"
                    )
            except Exception as br_err:
                logger.debug(f"Delayed bridge recheck: {br_err}")

        threading.Thread(
            target=_delayed_bridge_recheck,
            name="mscodebase-bridge-recheck",
            daemon=True,
        ).start()
    except Exception:
        pass

    return mcp


def _register_notification_broker(mcp, services):
    """Привязывает NotificationBroker к JSON-RPC сессии через initialized handler.

    Когда Zed присылает notifications/initialized, session уже создана.
    Захватываем её через request_context и сохраняем в брокере.
    """
    try:
        from mcp.types import InitializedNotification
        from src.core.notification_broker import NotificationBroker

        broker = services.resolve(NotificationBroker)
        server = mcp._mcp_server

        # Также устанавливаем брокер для error_boundary
        from src.core.error_handler import set_notification_broker as _set_err_broker
        _set_err_broker(broker)

        async def _on_initialized(notification: InitializedNotification):
            """Хендлер: клиент подтвердил инициализацию — сессия готова."""
            try:
                # request_context.session доступен только внутри MCP-хендлера
                ctx = server.request_context
                session = ctx.session
                broker.attach_session(session)
            except LookupError:
                logger.warning("Broker: request_context не доступен (вне запроса)")
            except Exception as e:
                logger.error(f"Broker: ошибка захвата сессии: {e}")

        # Регистрируем хендлер на нотификацию initialized
        server.notification_handlers[InitializedNotification] = _on_initialized
        logger.debug("NotificationBroker: хендлер initialized зарегистрирован")

    except Exception as e:
        logger.warning(f"NotificationBroker: не удалось зарегистрировать: {e}")


def _normalize_dashboard_path(path: str) -> str:
    """Нормализует Windows-путь для zed://file/ URI.

    Rust-расширение Zed (особенно под GitBash) ожидает URI с прямыми слэшами.
    Пример: C:\\Users\\misha\\file.py → C:/Users/misha/file.py
    """
    return path.replace("\\", "/")


def _register_extension_handlers(mcp, services):
    """Регистрирует JSON-RPC методы для Rust/WASM расширения.

    Методы:
    - msccodebase/get_dashboard — генерация Markdown дашборда с zed://file/ ссылками
    - msccodebase/force_reindex — принудительная переиндексация
    - msccodebase/clear_memory — очистка кэша памяти
    """
    try:
        server = mcp._mcp_server
        from src.mcp.tools.base import resolve_indexer_for_request
        from src.mcp.server import resolve_project_root as _rpr

        # Multi-window: default project_root для дашборда (per-call tools
        # резолвят свой).
        default_project_root = _rpr()

        if not (hasattr(server, "request_handlers") and isinstance(server.request_handlers, dict)):
            return

        # ─── msccodebase/get_dashboard ─────────────────────
        async def _handle_get_dashboard(params) -> str:
            """Генерирует Markdown дашборд с НОРМАЛИЗОВАННЫМИ путями.

            Все пути в zed://file/ URI принудительно конвертируются
            из backslashes в forward slashes для совместимости с Zed/GitBash.
            """
            try:
                # Multi-window: резолвим per-project indexer (если передан
                # params.project_root) или default.
                requested_root = (params or {}).get("project_root", "") if isinstance(params, dict) else ""
                idx = resolve_indexer_for_request(
                    services, explicit_project_root=requested_root or None,
                )
                stats = idx.get_status()
                chunks = stats.get("total_chunks", 0)
                files = stats.get("unique_files", 0)

                # Нормализуем пути для zed://file/ URI
                db_path = _normalize_dashboard_path(str(idx.db_path))
                root = _normalize_dashboard_path(str(idx.project_path))

                md = f"""# 🏗 MSCodeBase Architecture Dashboard

## 📊 Index Status
- **Chunks:** {chunks}
- **Files:** {files}
- **DB:** `{db_path}`

## 📁 Project: {project_root.name}
- [**src/core/**](zed://file/{root}/src/core/)
- [**tests/**](zed://file/{root}/tests/)

## 🛠 Commands
- [Trigger Full Reindex](command:mscodebase:trigger-full-reindex)
- [Clear Memory Cache](command:mscodebase:clear-project-memory)
"""
                return md
            except Exception as e:
                return f"# ❌ Dashboard Error\n\n{str(e)}"

        server.request_handlers["mscodebase/get_dashboard"] = _handle_get_dashboard

        # ─── msccodebase/force_reindex ────────────────────
        async def _handle_force_reindex(params) -> str:
            """Принудительная переиндексация.

            Multi-window: params.project_root задаёт какой проект переиндексировать.
            """
            import asyncio
            try:
                requested_root = (params or {}).get("project_root", "") if isinstance(params, dict) else ""
                idx = resolve_indexer_for_request(
                    services, explicit_project_root=requested_root or None,
                )
                target = idx.project_path
                indexed = await asyncio.to_thread(idx.index_project, target)
                return f'{{"status": "ok", "files": {indexed}, "project": "{target.name}"}}'
            except Exception as e:
                return f'{{"status": "error", "message": "{e}"}}'

        server.request_handlers["mscodebase/force_reindex"] = _handle_force_reindex

        # ─── msccodebase/clear_memory ─────────────────────
        async def _handle_clear_memory(params) -> str:
            """Очистка кэша памяти проекта (multi-window)."""
            try:
                requested_root = (params or {}).get("project_root", "") if isinstance(params, dict) else ""
                idx = resolve_indexer_for_request(
                    services, explicit_project_root=requested_root or None,
                )
                if hasattr(idx, "_symbol_index") and idx._symbol_index:
                    idx._symbol_index._definitions.clear()
                return f'{{"status": "ok", "project": "{idx.project_path.name}"}}'
            except Exception as e:
                return f'{{"status": "error", "message": "{e}"}}'

        server.request_handlers["mscodebase/clear_memory"] = _handle_clear_memory

        logger.info("🌉 Extension JSON-RPC handlers registered (3 methods)")

    except Exception as e:
        logger.warning(f"Extension handlers: {e}")


def _trigger_auto_index_if_empty(services):
    """Запускает фоновую индексацию, если индекс пуст.

    Multi-window: индексирует только default project_root (если пустой).
    Остальные проекты индексируются по запросу через index_project_dir.

    Self-indexing guard (INC-6BCB-v2): если project_path == _ext_root
    (т.е. resolve_project_root упал в fallback), НЕ индексируем —
    иначе проиндексируем само расширение (~500MB исходников).
    Ждём реального project_root через bridge / PROJECT_PATH.
    """
    import asyncio

    try:
        from src.mcp.tools.base import resolve_indexer_for_request
        from src.mcp.server import resolve_project_root as _rpr

        try:
            indexer = resolve_indexer_for_request(services)
        except Exception:
            return

        # Self-indexing guard: ext_root означает fallback (project не определён).
        try:
            if indexer.project_path.resolve() == _ext_root.resolve():
                logger.info(
                    "⏸ Auto-index: project_root == ext_root (fallback). "
                    "Пропускаем до появления реального project_root."
                )
                return
        except Exception:
            pass

        status = indexer.get_status()
        if status.get("total_chunks", 0) == 0:
            logger.info("🔄 Индекс пуст — запускаю фоновую индексацию (lazy)...")

            async def _auto_index():
                try:
                    target = indexer.project_path
                    logger.info(f"🔄 Индексация: {target.name}")
                    indexed = await asyncio.to_thread(
                        indexer.index_project, target
                    )
                    logger.info(f"✅ Авто-индексация: {indexed} файлов")
                except Exception as e:
                    logger.warning(f"Авто-индексация не удалась: {e}")
                    logger.info("Выполните index_project_dir(path) вручную")

            # КРИТИЧНО (INC-6BCB): НЕ ВЫЗЫВАЕМ loop.run_until_complete() —
            # он блокирует создание сервера и не даёт Zed ответить по stdio.
            # Если loop ещё не запущен (create_mcp_server вызывается до
            # mcp.run_stdio_async()), индексация будет запущена позже
            # через тот же ensure_future.
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(_auto_index())
                else:
                    # Loop ещё не запущен. НЕ блокируем — просто пропускаем.
                    # Индексация может быть запущена позже через явный вызов.
                    logger.debug(
                        "Event loop не запущен — auto-index будет пропущен. "
                        "Запустите index_project_dir() вручную."
                    )
            except RuntimeError:
                pass
        else:
            logger.info(f"Индекс не пуст ({status.get('total_chunks', 0)} чанков)")
    except Exception as e:
        logger.debug(f"Авто-индексация: {e}")


def _register_all_tools(mcp, services):
    """Регистрирует все 36 MCP-инструментов через DI контейнер.

    Каждый инструмент — отдельный class с constructor injection,
    задекорированный @error_boundary.
    """
    from src.mcp.tools.search_tools import (
        SearchCodeTool,
        GetSymbolInfoTool,
        ImpactAnalysisTool,
    )
    from src.mcp.tools.indexing_tools import (
        NotifyChangeTool,
        IndexProjectDirTool,
        IndexHealthTool,
    )
    from src.mcp.tools.git_tools import (
        GetBranchInfoTool,
        GetCommitHistoryTool,
        GetFileHistoryTool,
    )
    from src.mcp.tools.system_tools import (
        GetIndexStatusTool,
        GetIndexProgressTool,
        GetIndexTimelineTool,
        WatcherStatusTool,
        GetLogsTool,
        GetHealthReportTool,
        PredictEtaTool,
        RunHealthCheckTool,
        ReadLiveFileTool,
    )
    from src.mcp.tools.analysis_tools import (
        StructuralSearchTool,
        GetRepoMapTool,
        GetRepoRankTool,
        ScanChangesTool,
        GenerateChunkSummariesTool,
    )
    from src.mcp.tools.graph_tools import (
        CrossRepoSearchTool,
        CrossProjectDepsTool,
        GraphQueryTool,
        GetRelatedFilesTool,
    )
    from src.mcp.tools.investigation_tools import (
        GetBugCorrelationTool,
        GetHotspotsTool,
        FindSimilarBugsTool,
    )
    from src.mcp.tools.lifecycle_tools import (
        SubmitBackgroundTaskTool,
        GetTaskStatusTool,
        VerifyActionTool,
    )

    # Список всех инструментов для регистрации
    tool_classes = [
        # Search (3)
        SearchCodeTool,
        GetSymbolInfoTool,
        ImpactAnalysisTool,
        # Indexing (3)
        NotifyChangeTool,
        IndexProjectDirTool,
        IndexHealthTool,
        # Git (3)
        GetBranchInfoTool,
        GetCommitHistoryTool,
        GetFileHistoryTool,
        # System (9)
        GetIndexStatusTool,
        GetIndexProgressTool,
        GetIndexTimelineTool,
        WatcherStatusTool,
        GetLogsTool,
        GetHealthReportTool,
        PredictEtaTool,
        RunHealthCheckTool,
        ReadLiveFileTool,
        # Analysis (5)
        StructuralSearchTool,
        GetRepoMapTool,
        GetRepoRankTool,
        ScanChangesTool,
        GenerateChunkSummariesTool,
        # Graph (4)
        CrossRepoSearchTool,
        CrossProjectDepsTool,
        GraphQueryTool,
        GetRelatedFilesTool,
        # Investigation (3)
        GetBugCorrelationTool,
        GetHotspotsTool,
        FindSimilarBugsTool,
        # Lifecycle (3)
        SubmitBackgroundTaskTool,
        GetTaskStatusTool,
        VerifyActionTool,
    ]

    # Регистрируем каждый инструмент.
    # ВАЖНО (INC-6BCB-fallback): try/except вокруг каждого tool,
    # чтобы один сломанный __init__ не убивал все 36.
    registered = 0
    failed = []
    for tool_cls in tool_classes:
        try:
            instance = tool_cls(services)
            mcp.tool(name=instance.name)(instance.execute)
            registered += 1
            logger.debug(f"  🔧 Tool registered: {instance.name}")
        except Exception as e:
            failed.append((tool_cls.__name__, str(e)))
            logger.error(
                f"  ❌ Tool {tool_cls.__name__} failed to register: {e}",
                exc_info=True,
            )
    if failed:
        logger.warning(
            f"⚠️ {len(failed)}/{len(tool_classes)} tools failed to register: "
            f"{[n for n, _ in failed]}"
        )
    else:
        logger.info(f"✅ Все {registered} инструментов зарегистрированы")

    # ─── Intelligence Layer (10 инструментов) ──────
    # Multi-window (INC-6BCB-v2): Indexer/Searcher/SymbolIndex больше НЕ
    # зарегистрированы как singleton (см. di_container.py — Indexer-ы
    # per-project через ProjectIndexerRegistry). Используем
    # resolve_indexer_for_request() для получения per-project инстанса.
    try:
        from src.core.intelligence_layer import (
            ProjectIntelligenceLayer,
            register_intelligence_tools,
        )
        from src.mcp.tools.base import resolve_indexer_for_request

        idx = resolve_indexer_for_request(services)
        intel_layer = ProjectIntelligenceLayer(
            project_path=idx.project_path,
            indexer=idx,
            searcher=idx.searcher,
            symbol_index=idx._symbol_index,
        )
        register_intelligence_tools(mcp, intel_layer)
        logger.info("  🧠 Intel tools registered (10 tools)")
    except Exception as e:
        logger.warning(f"  ⚠️ Intel layer not registered: {e}")

    logger.info(f"✅ Все инструменты зарегистрированы ({len(tool_classes)}+10)")


def _register_system_prompt(mcp):
    """Регистрирует mscodebase-rules prompt для AI-агента."""
    from src.core.config import get_config

    mcp_prompt_text = """
# MSCODEBASE INTELLIGENCE CORE SYSTEM RULES

You operate under a strict deterministic execution matrix...

## 1. MCP PRIORITY RULES
- For ANY question about code → `search_code` FIRST
- If `get_index_status` returns chunks=0 → index_project_dir first
- If chunks > 0 → search_code for semantic, get_symbol_info for exact

## 2. RECONNAISSANCE BEFORE ACTION
- NEVER guess line numbers. Use get_symbol_info or grep before read_file.
- CONTEXT BUDGET: maximum 50 lines per read_file call.
- NEVER ingest entire files.

## 3. ERROR HANDLING
- If MCP tool returns error → pivot, don't retry same params
- Use get_logs for diagnostics
- Report exact error signatures

## 4. PATH PROTOCOL
- Native Windows paths (backslashes) for MCP tools
- Relative paths for notify_change (from project root)
- Absolute paths for project_root params
"""
    mcp.prompt(name="mscodebase-rules", description="Системные правила для работы с кодовой базой MSCodeBase")(
        lambda: mcp_prompt_text
    )


# ══════════════════════════════════════════════════════════
# Heartbeat — Anti-Orphan защита
# Вынесено в DI-класс (см. INC-53EC / REFC-11): глобальные переменные
# на module-level ломались при двух инстансах MCP (global+project).
# ══════════════════════════════════════════════════════════


class HeartbeatService:
    """Heartbeat-сервис для Anti-Orphan защиты.

    Идемпотентен: можно создавать несколько экземпляров (например, для
    отдельных MCP-инстансов). Все состояние инкапсулировано.
    """

    def __init__(
        self,
        interval: float = 30.0,
        timeout: float = 90.0,
        check_interval: float = 15.0,
    ):
        self.interval = interval
        self.timeout = timeout
        self.check_interval = check_interval
        self._parent_pid: Optional[int] = None
        self._last_heartbeat_time: float = 0.0
        self._task: Optional[asyncio.Task] = None
        self._lock = threading.Lock()
        self._running = False

    def init(self) -> None:
        """Захватываем родительский PID при старте."""
        with self._lock:
            self._parent_pid = os.getppid()
            self._last_heartbeat_time = time.time()
        logger.info(f"💓 Heartbeat инициализирован. Parent PID: {self._parent_pid}")

    def beat(self) -> None:
        """Обновляет время последнего heartbeat (вызов из хендлера)."""
        with self._lock:
            self._last_heartbeat_time = time.time()

    def is_parent_alive(self) -> bool:
        """Проверяет, жив ли родительский процесс."""
        with self._lock:
            pid = self._parent_pid
        if pid is None:
            return True
        try:
            if sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return kernel32.GetLastError() != 87  # ERROR_INVALID_PARAMETER = мёртв
            else:
                os.kill(pid, 0)
                return True
        except (ProcessLookupError, PermissionError, OSError):
            return False
        except Exception:
            return True  # fallback: не можем проверить — считаем живым

    async def _monitor(self) -> None:
        """Фоновая задача: проверяет здоровье соединения."""
        logger.info(
            f"💓 Heartbeat monitor запущен "
            f"(check={self.check_interval}s, timeout={self.timeout}s)"
        )
        while self._running:
            await asyncio.sleep(self.check_interval)
            try:
                with self._lock:
                    elapsed = time.time() - self._last_heartbeat_time
                if elapsed > self.timeout:
                    logger.warning(
                        f"💔 Heartbeat таймаут: {elapsed:.0f}s без пинга"
                    )
                    self._shutdown(f"Heartbeat timeout: {elapsed:.0f}s")
                    return
                if not self.is_parent_alive():
                    logger.warning(
                        f"💔 Родительский процесс (Zed) мёртв (PID: {self._parent_pid})"
                    )
                    self._shutdown("Parent process died")
                    return
            except asyncio.CancelledError:
                logger.info("💓 Heartbeat monitor остановлен")
                return
            except Exception as e:
                logger.error(f"Heartbeat monitor error: {e}")

    def _shutdown(self, reason: str) -> None:
        """Graceful shutdown: сначала atexit-обработчики, потом _exit."""
        logger.warning(f"🛑 Graceful shutdown: {reason}")
        try:
            from src.core.index_guard import IndexGuard
            db_path = Path.cwd() / ".codebase_indices" / "lancedb_v2"
            if db_path.exists():
                IndexGuard(db_path, Path.cwd())
        except Exception:
            pass
        # atexit-обработчики (SafePathManager.cleanup и т.д.) сработают
        # только при sys.exit. os._exit их обходит, теряя данные.
        # Мы всё равно вызываем os._exit потому что FastMCP застрял
        # в stdio-блокирующем режиме и не реагирует на sys.exit.
        # Но в начале пытаемся дать шанс atexit.
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)

    def start_monitor(self) -> None:
        """Запускает фоновый мониторинг (если ещё не запущен)."""
        with self._lock:
            if self._running:
                return
            self._running = True
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._task = asyncio.ensure_future(self._monitor())
                logger.info("💓 Heartbeat monitor started")
        except RuntimeError:
            logger.debug("Heartbeat monitor: event loop not ready")


# Глобальный экземпляр для обратной совместимости с существующими вызовами.
_heartbeat_service = HeartbeatService()


def _init_heartbeat() -> None:
    _heartbeat_service.init()


def _update_heartbeat() -> None:
    _heartbeat_service.beat()


def _is_parent_alive() -> bool:
    return _heartbeat_service.is_parent_alive()


async def _heartbeat_monitor() -> None:
    await _heartbeat_service._monitor()


def _graceful_shutdown(reason: str) -> None:
    _heartbeat_service._shutdown(reason)


def _start_heartbeat_monitor(mcp) -> None:
    """Регистрирует хендлер heartbeat и запускает фоновый мониторинг."""
    try:
        server = mcp._mcp_server
        if hasattr(server, "request_handlers") and isinstance(server.request_handlers, dict):

            async def _on_heartbeat(params):
                _update_heartbeat()
                return {}

            server.request_handlers["mscodebase/heartbeat"] = _on_heartbeat
            logger.debug("💓 Heartbeat handler registered")

        _heartbeat_service.start_monitor()
    except Exception as e:
        logger.warning(f"Heartbeat: {e}")


# ══════════════════════════════════════════════════════════
# Точка входа
# ══════════════════════════════════════════════════════════

def run_server(original_stdout=None):
    """Запускает MCP-сервер через stdio."""
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
