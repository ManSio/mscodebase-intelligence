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

# ══════════════════════════════════════════════════════════════
# Счётчики для измерения эффективности (telemetry)
# ══════════════════════════════════════════════════════════════

_COUNTERS: dict = {
    "can_execute_calls": 0,
    "verdict_ready": 0,
    "verdict_blocked_system_path": 0,
    "verdict_blocked_not_ready": 0,
    "verdict_blocked_failed": 0,
    "verdict_blocked_resolution": 0,
    "verdict_blocked_registry_error": 0,
    "warnings_bridge_not_synced": 0,
    "warnings_indexing_in_progress": 0,
    "warnings_just_started": 0,
    "total_wait_time_sec": 0.0,
}


def get_counters() -> dict:
    """Возвращает копию счётчиков для диагностики."""
    return dict(_COUNTERS)


def reset_counters() -> None:
    """Сбрасывает все счётчики (для тестов)."""
    for k in _COUNTERS:
        _COUNTERS[k] = 0


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
        import time as _time
        _t0 = _time.time()
        _COUNTERS["can_execute_calls"] += 1
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
            from src.core.indexing.project_indexer_registry import ProjectState

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
            _COUNTERS["verdict_blocked_registry_error"] += 1
            return ExecutionVerdict(
                ok=False,
                reason="registry_error",
                detail=str(e),
            )

        _COUNTERS["total_wait_time_sec"] += _time.time() - _t0

        # Layer 4: проверка runtime (passport)
        try:
            from src.core.passport import RUN_STARTED_AT
            uptime = time.time() - RUN_STARTED_AT
            if uptime < 3.0:
                warnings.append(f"MCP just started ({uptime:.0f}s ago)")
                _COUNTERS["warnings_just_started"] += 1
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        _COUNTERS["verdict_ready"] += 1
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
        recommended_action: строка с рекомендуемым действием ("run intel_trigger_reindex",
            "wait for LSP sync", "check logs" или None).
        confidence: уверенность в вердикте (0.0–1.0). 1.0 = железобетонно.
    """

    _REASON_ACTIONS = {
        "ready": None,
        "system_path": "Open a user project instead of a system directory",
        "project_not_ready": "Run intel_trigger_reindex() then check via intel_get_job_status()",
        "project_failed": "Check MCP logs via get_logs()",
        "project_resolution_failed": "Set PROJECT_PATH env var or open a project in Zed",
        "registry_error": "Restart MCP or check logs",
    }

    _REASON_CONFIDENCE = {
        "ready": 1.0,
        "system_path": 1.0,
        "project_not_ready": 0.9,
        "project_failed": 0.95,
        "project_resolution_failed": 0.7,
        "registry_error": 0.5,
    }

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
        self.recommended_action = self._REASON_ACTIONS.get(reason)
        self.confidence = self._REASON_CONFIDENCE.get(reason, 0.5)

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:
        return (
            f"ExecutionVerdict(ok={self.ok}, reason={self.reason!r}, "
            f"state={self.state}, retry_after={self.retry_after}, "
            f"confidence={self.confidence})"
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
            "recommended_action": self.recommended_action,
            "confidence": self.confidence,
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
                lines.append("Action required: trigger reindex")
            if self.requires_bridge_sync:
                lines.append("Action required: wait for LSP sync")
            if self.requires_restart:
                lines.append("Action required: restart MCP")
            if self.recommended_action:
                lines.append(f"Recommended: {self.recommended_action}")
        return chr(10).join(lines)
