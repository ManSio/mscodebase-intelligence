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
            ExecutionVerdict с полями ok, reason, state, detail.
        """
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

        # Layer 2: проверка registry + state machine
        try:
            from src.core.di_container import ProjectIndexerRegistry as PIRKey
            from src.core.project_indexer_registry import ProjectState

            registry = self._services.resolve(PIRKey)
            state = registry.get_state(path)

            if state == ProjectState.UNINITIALIZED:
                # Проект ещё не создан — возможно, первый вызов.
                # Попробуем подождать готовности (timeout).
                state = await registry.wait_until_ready(path, timeout=timeout)
                if state == ProjectState.UNINITIALIZED:
                    return ExecutionVerdict(
                        ok=False,
                        reason="project_not_ready",
                        state=state.name,
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
                    detail=f"Project {path.name} failed to initialize. Check logs for details.",
                )

            if state not in (ProjectState.READY, ProjectState.INDEXING):
                return ExecutionVerdict(
                    ok=False,
                    reason="project_not_ready",
                    state=state.name,
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

        return ExecutionVerdict(
            ok=True,
            reason="ready",
            state=state.name if 'state' in dir() else "READY",
        )


class ExecutionVerdict:
    """Результат проверки готовности.

    Поля:
        ok: True если можно выполнять операцию.
        reason: короткая строка-причина (ready / system_path / project_not_ready / ...).
        state: текущее состояние проекта (если доступно).
        detail: человекочитаемое описание.
    """

    def __init__(
        self,
        ok: bool = False,
        reason: str = "",
        state: str = "UNKNOWN",
        detail: str = "",
    ):
        self.ok = ok
        self.reason = reason
        self.state = state
        self.detail = detail

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:
        return f"ExecutionVerdict(ok={self.ok}, reason={self.reason!r}, state={self.state})"
