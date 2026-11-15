"""Guard: деградации проводки MCP на SDK 2.x остаются явными, а не тихими.

На 2.x у `MCPServer` нет `_mcp_server`, поэтому:
- NotificationBroker не может привязать сессию (публичного API для кастомных
  серверных уведомлений нет) — брокер всё равно ставится в error_handler,
  публикация честно логирует drop, и в лог идёт ровно один WARNING;
- кастомные JSON-RPC методы (heartbeat/dashboard/force-reindex/clear_memory)
  не регистрируются (ADR-0008, решение 1).

Тест краснеет, если брокер перестанут устанавливать (тихая потеря канала) или
если деградация начнёт маскироваться под успешную регистрацию.
"""
from __future__ import annotations

import logging

import pytest

from src.core import error_handler
from src.mcp.server_factory import (
    _register_extension_handlers,
    _register_notification_broker,
)


class _Services:
    def __init__(self, broker) -> None:
        self.broker = broker

    def resolve(self, _cls):
        return self.broker


class _Broker:
    def __init__(self) -> None:
        self.session = None

    def attach_session(self, session) -> None:
        self.session = session


class _LegacyServer:
    """Минимальная форма `mcp._mcp_server` (1.x)."""

    def __init__(self) -> None:
        self.notification_handlers: dict = {}
        self.request_handlers: dict = {}
        self.request_context = None


class _LegacyMCP:
    def __init__(self) -> None:
        self._mcp_server = _LegacyServer()


class _ModernMCP:
    """Форма `MCPServer` (2.x): `_mcp_server` отсутствует."""


@pytest.fixture(autouse=True)
def _restore_error_broker():
    saved = error_handler._error_broker
    yield
    error_handler._error_broker = saved


def test_v1_broker_is_installed_and_handler_registered():
    broker = _Broker()
    mcp = _LegacyMCP()

    _register_notification_broker(mcp, _Services(broker))

    assert error_handler._error_broker is broker
    assert len(mcp._mcp_server.notification_handlers) == 1


def test_v2_broker_is_installed_but_push_channel_warns_once(caplog):
    broker = _Broker()
    mcp = _ModernMCP()

    with caplog.at_level(logging.WARNING, logger="mscodebase"):
        _register_notification_broker(mcp, _Services(broker))

    assert error_handler._error_broker is broker, "брокер пропал молча"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "2.x" in warnings[0].getMessage()
    assert "ADR-0008" in warnings[0].getMessage()


def test_v2_extension_handlers_are_skipped_without_noise(caplog):
    mcp = _ModernMCP()

    with caplog.at_level(logging.DEBUG, logger="mscodebase"):
        _register_extension_handlers(mcp, _Services(_Broker()))

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_v1_extension_handlers_register_three_methods():
    mcp = _LegacyMCP()

    _register_extension_handlers(mcp, _Services(_Broker()))

    registered = set(mcp._mcp_server.request_handlers)
    assert registered == {
        "mscodebase/get_dashboard",
        "mscodebase/force_reindex",
        "mscodebase/clear_memory",
    }
