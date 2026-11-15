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
async def test_huge_budget_is_clamped(monkeypatch):
    """`inf`/`1e300` из env не должны давать вечное ожидание."""
    tool = _Tool()
    for raw in ("inf", "1e300", 1e9):
        monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", str(raw))
        assert tool._index_wait_budget() == MCPTool._INDEX_WAIT_MAX_S


@pytest.mark.asyncio
async def test_nan_budget_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "nan")
    tool = _Tool()
    assert tool._index_wait_budget() == MCPTool._INDEX_WAIT_DEFAULT_S


def test_empty_index_hint_distinguishes_building_from_not_started():
    """Совет обязан отличать «строится» от «не запускалась»."""
    class _Indexer:
        project_path = "D:/proj"

    building = MCPTool._empty_index_hint(_Indexer(), {"is_reindexing": True})
    idle = MCPTool._empty_index_hint(_Indexer(), {})

    assert "being built" in building
    assert "progress" in building
    assert "не запускалась" in idle
    assert "codebase(action='index'" in idle



@pytest.mark.asyncio
async def test_wait_does_not_block_event_loop(monkeypatch):
    """Пока ждём, event loop обязан тикать: блокирующий sleep даёт 0 тиков.

    Ревью 2026-11-16: прежняя версия (poll_s=0.05, 10 тиков по 0.02) оставалась
    зелёной при замене `await asyncio.sleep` на `time.sleep` — блокировки были
    короче интервала тикера. Здесь шаг ожидания 0.3 с: синхронный sleep съедал бы
    весь этот отрезок, и тикер не успевал ни разу.
    """
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "1.0")
    indexer = _Indexer(readiness_after=10_000)
    tool = _Tool()
    ticks: list[float] = []
    started = asyncio.get_running_loop().time()

    async def ticker():
        for _ in range(200):
            await asyncio.sleep(0.01)
            ticks.append(asyncio.get_running_loop().time() - started)

    await asyncio.gather(tool._wait_for_first_chunks(indexer, poll_s=0.3), ticker())

    # Метрика — не число тиков (между итерациями `to_thread` они появятся всё
    # равно), а максимальный разрыв: блокирующий `time.sleep(0.3)` съедает
    # целых 0.3 с без единого тика, `await asyncio.sleep(0.3)` — нет.
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert gaps, "тикер не сделал ни одного шага"
    assert max(gaps) < 0.15, (
        f"event loop блокировался: максимальный разрыв между тиками {max(gaps):.3f} с"
    )

