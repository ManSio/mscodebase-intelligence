"""Guard: серверные уведомления MCP (progress/message) и их безопасность.

Замер 2026-11-16: за 56 живых вызовов сервер не прислал ни одного уведомления
(`notifications=0`), а индексация шла молча.
"""
from __future__ import annotations

import pytest

from src.mcp import notifications


class _Session:
    def __init__(self, fail: bool = False):
        self.calls: list[dict] = []
        self.fail = fail

    async def send_log_message(self, level, data, logger=None):
        if self.fail:
            raise RuntimeError("transport is gone")
        self.calls.append({"level": level, "data": data, "logger": logger})

    async def send_progress_notification(self, *, progress_token, progress, total=None,
                                         message=None):
        if self.fail:
            raise RuntimeError("transport is gone")
        self.calls.append({"token": progress_token, "progress": progress, "total": total})


@pytest.fixture(autouse=True)
def _clean_session():
    notifications.reset_session()
    yield
    notifications.reset_session()


@pytest.mark.asyncio
async def test_notify_log_without_session_is_a_noop():
    assert await notifications.notify_log("info", "никому") is False


@pytest.mark.asyncio
async def test_notify_log_sends_level_and_logger():
    session = _Session()
    notifications._session = session

    assert await notifications.notify_log("warning", "медленно", "mscodebase.indexer") is True
    assert session.calls == [
        {"level": "warning", "data": "медленно", "logger": "mscodebase.indexer"}
    ]


@pytest.mark.asyncio
async def test_notify_log_normalizes_unknown_level():
    session = _Session()
    notifications._session = session

    await notifications.notify_log("panic", "x")
    assert session.calls[0]["level"] == "info"


@pytest.mark.asyncio
async def test_notify_log_swallows_transport_errors():
    notifications._session = _Session(fail=True)
    assert await notifications.notify_log("info", "x") is False


@pytest.mark.asyncio
async def test_notify_progress_uses_token():
    session = _Session()
    notifications._session = session

    assert await notifications.notify_progress(5, 10, "половина", progress_token="tok") is True
    assert session.calls[0] == {"token": "tok", "progress": 5, "total": 10}


def test_bind_outside_request_does_not_raise():
    notifications.bind_session_from_request()
    assert notifications.get_session() is None
