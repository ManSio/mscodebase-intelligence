"""Meta-tools: объединяют группы родственных инструментов в один `action`-диспетчер.

По аналогии с WriteTool — один инструмент с параметром action,
который диспатчит на соответствующие низкоуровневые инструменты.

Использует `__wrapped__` для обхода error_boundary оригинальных классов,
чтобы избежать двойного декорирования (meta-tool уже имеет свой error_boundary).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.meta_tools")


class IndexTool(MCPTool):
    """index — единый инструмент для операций индексации.

    Доступные action:
    - "notify"    — обновить индекс одного файла (NotifyChangeTool)
    - "reindex"   — полная переиндексация проекта (IndexProjectDirTool)
    - "status"    — статистика заполнения векторной базы (GetIndexStatusTool)
    - "progress"  — прогресс индексации для всех проектов (GetIndexProgressTool)
    - "timeline"  — временная шкала индексации (GetIndexTimelineTool)
    - "health"    — диагностика и самовосстановление индекса (IndexHealthTool)
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="index")

    @error_boundary("index", timeout_ms=300000)
    async def execute(
        self,
        action: str,
        # NotifyChange params
        file_path: str = "",
        # IndexProjectDir params
        path: str = "",
        # IndexHealth / GetIndexStatus params
        project_root: str = "",
        # general passthrough
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute an index operation.

        Args:
            action: One of: notify, reindex, status, progress, timeline, health
            file_path: Path to file (notify)
            path: Project path to index (reindex)
            project_root: Project root (status, progress, timeline, health)
            kwargs: Optional extra kwargs passthrough
        """
        action_map = {
            "notify": self._action_notify,
            "reindex": self._action_reindex,
            "status": self._action_status,
            "progress": self._action_progress,
            "timeline": self._action_timeline,
            "health": self._action_health,
        }

        handler = action_map.get(action)
        if handler is None:
            return (
                f"🚫 **Unknown action:** `{action}`\n\n"
                f"Available: notify, reindex, status, progress, timeline, health"
            )

        # Pass through all kwargs (except control keys)
        kw = {
            k: v
            for k, v in locals().items()
            if k not in ("self", "action", "handler", "action_map", "kw")
        }
        return await handler(**kw)

    async def _action_notify(self, **kw) -> str:
        from src.mcp.tools.indexing_tools import NotifyChangeTool

        tool = NotifyChangeTool(self._services)
        return await NotifyChangeTool.execute.__wrapped__(
            tool,
            file_path=kw.get("file_path", ""),
            kwargs=kw.get("kwargs"),
        )

    async def _action_reindex(self, **kw) -> str:
        from src.mcp.tools.indexing_tools import IndexProjectDirTool

        tool = IndexProjectDirTool(self._services)
        target = kw.get("path") or kw.get("project_root", "")
        return await IndexProjectDirTool.execute.__wrapped__(
            tool,
            path=target,
            kwargs=kw.get("kwargs"),
        )

    async def _action_status(self, **kw) -> str:
        from src.mcp.tools.system_tools import GetIndexStatusTool

        tool = GetIndexStatusTool(self._services)
        return await GetIndexStatusTool.execute.__wrapped__(
            tool,
            kwargs=kw.get("kwargs"),
        )

    async def _action_progress(self, **kw) -> dict:
        from src.mcp.tools.system_tools import GetIndexProgressTool

        tool = GetIndexProgressTool(self._services)
        return await GetIndexProgressTool.execute.__wrapped__(
            tool,
            kwargs=kw.get("kwargs"),
        )

    async def _action_timeline(self, **kw) -> dict:
        from src.mcp.tools.system_tools import GetIndexTimelineTool

        tool = GetIndexTimelineTool(self._services)
        return await GetIndexTimelineTool.execute.__wrapped__(
            tool,
            kwargs=kw.get("kwargs"),
        )

    async def _action_health(self, **kw) -> dict:
        from src.mcp.tools.indexing_tools import IndexHealthTool

        tool = IndexHealthTool(self._services)
        return await IndexHealthTool.execute.__wrapped__(
            tool,
            project_root=kw.get("project_root", ""),
            kwargs=kw.get("kwargs"),
        )


class GitTool(MCPTool):
    """git — единый инструмент для git-операций.

    Доступные action:
    - "log"      — история коммитов (GetCommitHistoryTool)
    - "history"  — история изменений файла (GetFileHistoryTool)
    - "branch"   — информация о ветке (GetBranchInfoTool)
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="git")

    @error_boundary("git", timeout_ms=15000)
    async def execute(
        self,
        action: str,
        project_root: str = "",
        limit: int = 10,
        file_path: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a git operation.

        Args:
            action: One of: log, history, branch
            project_root: Project root path
            limit: Max commits to return (log)
            file_path: File path (history)
            kwargs: Optional extra kwargs passthrough
        """
        action_map = {
            "log": self._action_log,
            "history": self._action_history,
            "branch": self._action_branch,
        }

        handler = action_map.get(action)
        if handler is None:
            return (
                f"🚫 **Unknown action:** `{action}`\n\n"
                f"Available: log, history, branch"
            )

        kw = {
            k: v
            for k, v in locals().items()
            if k not in ("self", "action", "handler", "action_map", "kw")
        }
        return await handler(**kw)

    async def _action_log(self, **kw) -> dict:
        from src.mcp.tools.git_tools import GetCommitHistoryTool

        tool = GetCommitHistoryTool(self._services)
        return await GetCommitHistoryTool.execute.__wrapped__(
            tool,
            project_root=kw.get("project_root", ""),
            limit=kw.get("limit", 10),
            kwargs=kw.get("kwargs"),
        )

    async def _action_history(self, **kw) -> dict:
        from src.mcp.tools.git_tools import GetFileHistoryTool

        tool = GetFileHistoryTool(self._services)
        return await GetFileHistoryTool.execute.__wrapped__(
            tool,
            project_root=kw.get("project_root", ""),
            file_path=kw.get("file_path", ""),
            kwargs=kw.get("kwargs"),
        )

    async def _action_branch(self, **kw) -> dict:
        from src.mcp.tools.git_tools import GetBranchInfoTool

        tool = GetBranchInfoTool(self._services)
        return await GetBranchInfoTool.execute.__wrapped__(
            tool,
            project_root=kw.get("project_root", ""),
            kwargs=kw.get("kwargs"),
        )


class SystemTool(MCPTool):
    """system — единый инструмент для системных операций.

    Доступные action:
    - "health"    — полная диагностика системы (GetHealthReportTool)
    - "logs"      — последние ошибки и предупреждения (GetLogsTool)
    - "read"      — чтение файла из LSP/диска (ReadLiveFileTool)
    - "counters"  — счётчики runtime (get_runtime_counters)
    - "passport"  — паспорт текущего процесса (debug_runtime_passport)
    - "watcher"   — статус компонентов индексации (WatcherStatusTool)
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="system")

    @error_boundary("system", timeout_ms=45000)
    async def execute(
        self,
        action: str,
        project_root: str = "",
        absolute_path: str = "",
        file_path: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a system operation.

        Args:
            action: One of: health, logs, read, counters, passport, watcher
            project_root: Project root (health, logs, watcher)
            absolute_path: Absolute file path (read)
            file_path: Relative file path (read)
            kwargs: Optional extra kwargs passthrough
        """
        action_map = {
            "health": self._action_health,
            "logs": self._action_logs,
            "read": self._action_read,
            "counters": self._action_counters,
            "passport": self._action_passport,
            "watcher": self._action_watcher,
        }

        handler = action_map.get(action)
        if handler is None:
            return (
                f"🚫 **Unknown action:** `{action}`\n\n"
                f"Available: health, logs, read, counters, passport, watcher"
            )

        kw = {
            k: v
            for k, v in locals().items()
            if k not in ("self", "action", "handler", "action_map", "kw")
        }
        return await handler(**kw)

    async def _action_health(self, **kw) -> dict:
        from src.mcp.tools.system_tools import GetHealthReportTool

        tool = GetHealthReportTool(self._services)
        return await GetHealthReportTool.execute.__wrapped__(
            tool,
            project_root=kw.get("project_root", ""),
            kwargs=kw.get("kwargs"),
        )

    async def _action_logs(self, **kw) -> dict:
        from src.mcp.tools.system_tools import GetLogsTool

        tool = GetLogsTool(self._services)
        return await GetLogsTool.execute.__wrapped__(
            tool,
            project_root=kw.get("project_root", ""),
            kwargs=kw.get("kwargs"),
        )

    async def _action_read(self, **kw) -> dict:
        from src.mcp.tools.system_tools import ReadLiveFileTool

        tool = ReadLiveFileTool(self._services)
        return await ReadLiveFileTool.execute.__wrapped__(
            tool,
            absolute_path=kw.get("absolute_path", ""),
            file_path=kw.get("file_path", ""),
        )

    async def _action_counters(self, **kw) -> str:
        """Runtime counters — делегирует в runtime_coordinator."""
        from src.core.runtime_coordinator import get_counters

        counters = get_counters()
        calls = counters.get("can_execute_calls", 0)
        ready = counters.get("verdict_ready", 0)
        blocked_pct = round((1 - ready / max(calls, 1)) * 100, 1)
        lines = [
            "📊 **Runtime Counters**\n",
            f"• **Checks:** `{calls}` | **Ready:** `{ready}` | **Blocked:** `{blocked_pct}%`",
        ]
        for k, v in counters.items():
            if k.startswith("verdict_blocked_") and v:
                reason = k.replace("verdict_blocked_", "").replace("_", " ")
                lines.append(f"• 🚫 {reason}: `{v}`")
        return "\n".join(lines)

    async def _action_passport(self, **kw) -> str:
        """Runtime passport — делегирует в server module constants."""
        import getpass
        import time
        from datetime import datetime

        from src.mcp.server import (
            _BUILD_ID,
            _RUN_ID,
            _RUN_PID,
            _RUN_SOURCE_FILE,
            _RUN_STARTED_AT,
            _default_project_root,
            _ext_root,
        )

        uptime_sec = round(time.time() - _RUN_STARTED_AT, 1)
        return (
            "🧬 **Runtime Passport**\n"
            f"• **RUN_ID:** `{_RUN_ID}`\n"
            f"• **BUILD_ID:** `{_BUILD_ID}`\n"
            f"• **PID:** `{_RUN_PID}`\n"
            f"• **Started:** `{datetime.fromtimestamp(_RUN_STARTED_AT).isoformat()}`\n"
            f"• **Uptime:** `{uptime_sec}s`\n"
            f"• **Source:** `{_RUN_SOURCE_FILE}`\n"
            f"• **User:** `{getpass.getuser()}`\n"
            f"• **Ext Root:** `{_ext_root}`\n"
            f"• **Project:** `{_default_project_root or 'N/A'}`"
        )

    async def _action_watcher(self, **kw) -> dict:
        from src.mcp.tools.system_tools import WatcherStatusTool

        tool = WatcherStatusTool(self._services)
        return await WatcherStatusTool.execute.__wrapped__(
            tool,
            kwargs=kw.get("kwargs"),
        )
