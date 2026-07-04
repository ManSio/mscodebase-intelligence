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
_env_project_root_raw = os.environ.get("PROJECT_PATH", "")
_env_project_root: Optional[Path] = None

# Разрешаем PROJECT_PATH при импорте (один раз)
if _env_project_root_raw:
    if "$ZED" in _env_project_root_raw:
        zed_root = os.environ.get("ZED_WORKTREE_ROOT")
        if zed_root:
            zed_path = Path(zed_root).resolve()
            if zed_path.exists() and zed_path != _ext_root:
                _env_project_root = zed_path
    else:
        _resolved = Path(_env_project_root_raw).resolve()
        if _resolved.exists() and _resolved.is_dir():
            _env_project_root = _resolved


def resolve_project_root(provided: str = "") -> Path:
    """Возвращает корень проекта для MCP-инструментов.

    Приоритет:
    1. Явно переданный provided
    2. LSP→MCP bridge (temp-файл от LSP)
    3. PROJECT_PATH из окружения
    4. ext_root если Git-репозиторий
    5. ZED_WORKTREE_ROOT env
    6. CWD
    7. ext_root как fallback
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

    if _env_project_root is not None:
        return _env_project_root

    if (_ext_root / ".git").exists():
        logger.debug(f"resolve_project_root: ext_root is git repo: {_ext_root}")
        return _ext_root

    zed_root = os.environ.get("ZED_WORKTREE_ROOT")
    if zed_root:
        zed_path = Path(zed_root).resolve()
        if zed_path.exists():
            logger.debug(f"resolve_project_root: ZED_WORKTREE_ROOT={zed_path}")
            return zed_path

    cwd = Path.cwd().resolve()
    if cwd != _ext_root:
        logger.debug(f"resolve_project_root: CWD={cwd}")
        return cwd

    logger.warning(f"resolve_project_root: fallback to ext_root={_ext_root}")
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

    # ─── 1. Project root ────────────────────────────
    project_root = resolve_project_root()
    logger.info(
        f"🏠 Project root: {project_root} "
        f"(CWD={Path.cwd().resolve()}, "
        f"PROJECT_PATH={os.environ.get('PROJECT_PATH', 'не установлен')})"
    )

    # ─── 2. DI Container ────────────────────────────
    from src.core.di_container import create_service_collection
    services = create_service_collection(project_root)

    # Настройка файлового логирования
    from src.core.log_manager import setup_project_logging
    setup_project_logging(project_root)
    logger.info("🚀 MCP-сервер запущен (DI Container ready)")

    # ─── 3. Регистрация инструментов ─────────────────
    _register_all_tools(mcp, services)

    # ─── 4. Системный prompt ─────────────────────────
    _register_system_prompt(mcp)

    # ─── 5. Авто-индексация при пустом индексе ───────
    _trigger_auto_index_if_empty(services)

    return mcp


def _trigger_auto_index_if_empty(services):
    """Запускает фоновую индексацию, если индекс пуст."""
    import asyncio

    try:
        from src.core.indexer import Indexer

        indexer = services.resolve(Indexer)
        status = indexer.get_status()
        if status.get("total_chunks", 0) == 0:
            logger.info("🔄 Индекс пуст — запускаю фоновую индексацию...")

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

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(_auto_index())
                else:
                    loop.run_until_complete(_auto_index())
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

    # Регистрируем каждый инструмент
    for tool_cls in tool_classes:
        instance = tool_cls(services)
        mcp.tool(name=instance.name)(instance.execute)
        logger.debug(f"  🔧 Tool registered: {instance.name}")

    # ─── Intelligence Layer (10 инструментов) ──────
    try:
        from src.core.intelligence_layer import (
            ProjectIntelligenceLayer,
            register_intelligence_tools,
        )
        from src.core.indexer import Indexer
        from src.core.searcher import Searcher
        from src.core.symbol_index import SymbolIndex

        intel_layer = ProjectIntelligenceLayer(
            project_path=resolve_project_root(),
            indexer=services.resolve(Indexer),
            searcher=services.resolve(Searcher),
            symbol_index=services.resolve(SymbolIndex),
        )
        register_intelligence_tools(mcp, intel_layer)
        logger.info("  🧠 Intel tools registered (10 tools)")
    except Exception as e:
        logger.warning(f"  ⚠️ Intel layer not registered: {e}")

    logger.info(f"✅ Все инструменты зарегистрированы ({len(tool_classes)}+13)")


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
