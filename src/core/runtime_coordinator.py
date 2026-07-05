"""
RuntimeCoordinator — единая точка принятия решения «можно ли выполнять MCP-запрос?».

Отвечает на один вопрос:
    Может ли система сейчас выполнить операцию для данного проекта?

Для ответа использует:
  • ProjectIndexerRegistry (состояние проекта)
  • LSP Bridge (синхронизация пути)
  • SystemArtifacts (проверка системного пути)

Ничего не ломает — существующие инструменты продолжают работать как раньше.
Новые инструменты могут использовать Coordinator вместо самостоятельного
опроса Registry + Bridge + StateMachine.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("mscodebase_server.coordinator")


class RuntimeCoordinator:
    """Единая точка для проверки готовности проекта.

    Usage:
        coord = RuntimeCoordinator(services)
        result = await coord.can_execute(project_path)
        if not result.ok:
            raise ToolError(result.reason)
    """

    def __init__(self, services: Any):
        self._services = services

    async def can_execute(
        self,
        project_path: Optional[Path] = None,
        timeout: float = 5.0,
    ) -> "ExecutionVerdict":
        """Проверяет, можно ли выполнять операцию для проекта.

        Args:
            project_path: путь к проекту (если None — ресолвится автоматически).
            timeout: макс. время ожидания готовности.

        Returns:
            ExecutionVerdict с полями ok, reason, state, detail,
            retry_after, requires_reindex, requires_bridge_sync, warnings.
        """
        warnings: list[str] = []
        try:
            from src.mcp.server import resolve_project_root
            path = project_path or resolve_project_root()
        except Exception as e:
            return ExecutionVerdict(ok=False, reason="project_resolution_failed", detail=str(e))

        # Layer 1: проверка, что путь не системный
        try:
            from src.core.system_artifacts import SystemArtifacts
            if SystemArtifacts.is_system_path(path):
                return ExecutionVerdict(
                    ok=False,
                    reason="system_path",
                    detail=f"Cannot execute operation on system directory: {path}",
                )
        except ImportError:
            pass

        # Layer 2: проверка bridge (LSP синхронизирован?)
        bridge_synced = False
        try:
            from src.core.lsp_project_bridge import read_project_from_bridge
            bp = read_project_from_bridge(max_wait=0.3)
            if bp is not None and bp.resolve() == path.resolve():
                bridge_synced = True
            else:
                warnings.append("LSP bridge not yet synchronized")
        except Exception:
            warnings.append("LSP bridge unavailable")

        # Layer 3: проверка registry + state machine
        try:
            from src.core.di_container import ProjectIndexerRegistry as PIRKey
            from src.core.project_indexer_registry import ProjectState

            registry = self._services.resolve(PIRKey)
            state = registry.get_state(path)

            if state == ProjectState.UNINITIALIZED:
                state = await registry.wait_until_ready(path, timeout=timeout)
                if state == ProjectState.UNINITIALIZED:
                    return ExecutionVerdict(
                        ok=False,
                        reason="project_not_ready",
                        state=state.name,
                        requires_reindex=True,
                        detail=(
                            f"Project {path.name} has not been initialized. "
                            "Try opening a file in the project or run index_project_dir()."
                        ),
                    )

            if state == ProjectState.FAILED:
                return ExecutionVerdict(
                    ok=False,
                    reason="project_failed",
                    state=state.name,
                    detail=f"Project {path.name} failed to initialize. Check logs.",
                )

            if state == ProjectState.INDEXING:
                warnings.append("Background indexing in progress")

            if state not in (ProjectState.READY, ProjectState.INDEXING):
                return ExecutionVerdict(
                    ok=False,
                    reason="project_not_ready",
                    state=state.name,
                    retry_after=2.0,
                    detail=(
                        f"Project {path.name} is {state.name}. "
                        "Try again in a few seconds."
                    ),
                )

        except Exception as e:
            return ExecutionVerdict(
                ok=False,
                reason="registry_error",
                detail=str(e),
            )

        # Layer 4: проверка runtime (passport)
        try:
            from src.mcp.server import _RUN_STARTED_AT
            uptime = time.time() - _RUN_STARTED_AT
            if uptime < 3.0:
                warnings.append(f"MCP just started ({uptime:.0f}s ago)")
        except Exception:
            pass

        return ExecutionVerdict(
            ok=True,
            reason="ready",
            state=state.name if 'state' in dir() else "READY",
            requires_bridge_sync=not bridge_synced,
            warnings=warnings,
        )


class ExecutionVerdict:
    """Результат проверки готовности — полноценный объект, не bool.

    Поля:
        ok: True если можно выполнять операцию.
        reason: короткая строка-причина (ready / system_path / project_not_ready / ...).
        state: текущее состояние проекта (если доступно).
        detail: человекочитаемое описание.
        retry_after: секунд до повторной попытки (0 = не retry).
        requires_reindex: True если нужна переиндексация.
        requires_bridge_sync: True если LSP не синхронизирован.
        requires_restart: True если нужен рестарт MCP.
        warnings: список предупреждений.
    """

    def __init__(
        self,
        ok: bool = False,
        reason: str = "",
        state: str = "UNKNOWN",
        detail: str = "",
        retry_after: float = 0.0,
        requires_reindex: bool = False,
        requires_bridge_sync: bool = False,
        requires_restart: bool = False,
        warnings: Optional[list[str]] = None,
    ):
        self.ok = ok
        self.reason = reason
        self.state = state
        self.detail = detail
        self.retry_after = retry_after
        self.requires_reindex = requires_reindex
        self.requires_bridge_sync = requires_bridge_sync
        self.requires_restart = requires_restart
        self.warnings = warnings or []

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:
        return (
            f"ExecutionVerdict(ok={self.ok}, reason={self.reason!r}, "
            f"state={self.state}, retry_after={self.retry_after})"
        )

    def to_dict(self) -> dict:
        """Сериализация в dict для JSON."""
        return {
            "ok": self.ok,
            "reason": self.reason,
            "state": self.state,
            "detail": self.detail,
            "retry_after": self.retry_after,
            "requires_reindex": self.requires_reindex,
            "requires_bridge_sync": self.requires_bridge_sync,
            "requires_restart": self.requires_restart,
            "warnings": self.warnings,
        }

    def to_human_readable(self) -> str:
        """Человекочитаемый диагноз для intel_explain_project_state."""
        lines = []
        if self.ok:
            lines.append(f"Project state: {self.state}")
            lines.append(f"Ready: {self.ok}")
            lines.append(f"Reason: {self.reason}")
            if self.warnings:
                lines.append(f"Warnings: {', '.join(self.warnings)}")
        else:
            lines.append(f"Cannot execute: {self.reason}")
            lines.append(f"Project state: {self.state}")
            lines.append(f"Details: {self.detail}")
            if self.retry_after > 0:
                lines.append(f"Retry after: {self.retry_after}s")
            if self.requires_reindex:
                lines.append(f"Action required: trigger reindex")
            if self.requires_bridge_sync:
                lines.append(f"Action required: wait for LSP sync")
            if self.requires_restart:
                lines.append(f"Action required: restart MCP")
        return chr(10).join(lines)
