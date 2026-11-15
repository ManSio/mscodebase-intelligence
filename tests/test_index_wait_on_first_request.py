"""Guard: первый запрос дожидается автоиндексации, а не падает «Index is empty».

Живой замер 2026-11-16: свежий проект (31 файл), `initialize` через ~7 с,
автоиндексация завершилась за ~1 с, но запрос приходил через 7 мс после
handshake — `investigate` отвечал `INDEX_NOT_READY` с советом «запусти
индексацию», хотя она уже шла. Теперь `require_ready_project` ждёт первые
чанки ограниченно (`MSCODEBASE_INDEX_WAIT_S`, по умолчанию 8 с).
"""
from __future__ import annotations

import asyncio

import pytest

from src.mcp.tools.base import MCPTool


class _Tool(MCPTool):
    """Минимальный наследник: проверяем только ожидание индекса."""

    def __init__(self):
        self.services = None

    async def execute(self, **kwargs):  # pragma: no cover - не вызывается
        return ""


class _Indexer:
    def __init__(self, readiness_after: int):
        self.calls = 0
        self.readiness_after = readiness_after

    def get_status(self):
        self.calls += 1
        chunks = 10 if self.calls > self.readiness_after else 0
        return {"total_chunks": chunks, "unique_files": chunks}


@pytest.mark.asyncio
async def test_waits_until_first_chunks(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "2")
    indexer = _Indexer(readiness_after=2)
    tool = _Tool()

    assert await tool._wait_for_first_chunks(indexer, poll_s=0.01) is True
    assert indexer.calls >= 3


@pytest.mark.asyncio
async def test_returns_false_when_budget_is_zero(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "0")
    indexer = _Indexer(readiness_after=0)
    tool = _Tool()

    assert await tool._wait_for_first_chunks(indexer, poll_s=0.01) is False
    assert indexer.calls == 0, "при нулевом бюджете опросов быть не должно"


@pytest.mark.asyncio
async def test_returns_false_after_timeout(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "0.15")
    indexer = _Indexer(readiness_after=10_000)
    tool = _Tool()

    assert await tool._wait_for_first_chunks(indexer, poll_s=0.02) is False
    assert indexer.calls >= 2


@pytest.mark.asyncio
async def test_bad_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "not-a-number")
    tool = _Tool()
    assert tool._index_wait_budget() == MCPTool._INDEX_WAIT_DEFAULT_S


@pytest.mark.asyncio
async def test_wait_does_not_block_event_loop(monkeypatch):
    """Пока ждём, другие корутины должны исполняться (sleep, не блокировка)."""
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "0.5")
    indexer = _Indexer(readiness_after=10_000)
    tool = _Tool()
    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(10):
            await asyncio.sleep(0.02)
            ticks += 1

    await asyncio.gather(tool._wait_for_first_chunks(indexer, poll_s=0.05), ticker())
    assert ticks == 10
