"""Серверные уведомления MCP: захват сессии и прогресс индексации.

Зачем: за 56 живых вызовов сервер не прислал ни одного уведомления
(`notifications=0`, замер 2026-11-16). Долгая индексация шла «молча» — хост
видел только ответ инструмента. Здесь:

- `bind_session_from_request()` — запоминает сессию из текущего MCP-запроса
  (ContextVar SDK доступен внутри обработчика, поэтому вызов делается из
  `MCPTool.require_ready_project`, который проходит каждый инструмент);
- `notify_log()` — отправляет `notifications/message` (логирование MCP),
  если сессия известна; любые сбои глотаются: уведомление не должно ломать
  инструмент.

Никакого нового состояния в протоколе не вводим: это стандартные
`send_log_message`/`send_progress_notification` из MCP SDK.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

__all__ = [
    "bind_session_from_request",
    "get_session",
    "reset_session",
    "notify_log",
    "notify_progress",
    "schedule",
]

logger = logging.getLogger("mscodebase.notifications")

_session: Optional[Any] = None


def bind_session_from_request() -> None:
    """Запоминает сессию текущего запроса (если мы внутри обработчика MCP)."""
    global _session
    if _session is not None:
        return
    try:
        from mcp.server.lowlevel.server import request_ctx

        ctx = request_ctx.get()
        session = getattr(ctx, "session", None)
        if session is not None:
            _session = session
            logger.debug("MCP session captured for server notifications")
    except Exception:  # noqa: BLE001 — вне запроса/другая версия SDK
        pass


def get_session() -> Optional[Any]:
    """Сессия, захваченная из последнего запроса (или None)."""
    return _session


def reset_session() -> None:
    """Сбрасывает захваченную сессию (для тестов и перезапуска)."""
    global _session
    _session = None


def schedule(coro, loop):
    """Ставит корутину в loop; при закрытом loop закрывает её без warning.

    `asyncio.run_coroutine_threadsafe` на закрытом loop бросает RuntimeError
    и оставляет корутину неawait-нутой (`coroutine ... was never awaited`).
    """
    import asyncio

    try:
        return asyncio.run_coroutine_threadsafe(coro, loop)
    except RuntimeError:
        close = getattr(coro, "close", None)
        if close is not None:
            close()
        return None


async def notify_log(level: str, message: str, logger_name: str = "mscodebase") -> bool:
    """Отправляет `notifications/message`. True — доставлено.

    `level` — по протоколу MCP: debug | info | notice | warning | error.
    """
    session = _session
    if session is None:
        return False
    if level not in ("debug", "info", "notice", "warning", "error"):
        level = "info"
    try:
        await session.send_log_message(level=level, data=message, logger=logger_name)
        return True
    except Exception as exc:  # noqa: BLE001 — уведомление не должно ломать работу
        logger.debug(f"notify_log failed: {exc}")
        return False


async def notify_progress(
    progress: float,
    total: Optional[float] = None,
    message: str = "",
    progress_token: Any = None,
) -> bool:
    """Отправляет `notifications/progress` (если у запроса был progressToken)."""
    session = _session
    if session is None:
        return False
    try:
        await session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message or None,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"notify_progress failed: {exc}")
        return False
