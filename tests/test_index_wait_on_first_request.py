"""Guard: первый запрос дожидается автоиндексации, а не падает «Index is empty».

Живой замер 2026-11-16: свежий проект (31 файл), `initialize` через ~7 с,
автоиндексация завершилась за ~1 с, но запрос приходил через 7 мс после
handshake — `investigate` отвечал `INDEX_NOT_READY` с советом «запусти
индексацию», хотя она уже шла. Теперь `require_ready_project` ждёт первые
чанки ограниченно (`MSCODEBASE_INDEX_WAIT_S`) и только пока индексация идёт.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from src.core.indexing import auto_index_state
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


# ── бюджет ожидания ────────────────────────────────────────────────


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


@pytest.mark.asyncio
async def test_default_budget_fits_the_shortest_tool_timeout():
    """Бюджет обязан быть меньше самого короткого `error_boundary` (5 с).

    Иначе честное «индекс пуст» превращается в TIMEOUT с ложным советом.
    """
    assert MCPTool._INDEX_WAIT_MAX_S < 5.0
    assert MCPTool._INDEX_WAIT_DEFAULT_S < 5.0


# ── само ожидание ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_waits_until_first_chunks(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "2")
    auto_index_state.mark_started()
    indexer = _Indexer(readiness_after=2)
    tool = _Tool()
    try:
        assert await tool._wait_for_first_chunks(indexer, poll_s=0.02) is True
    finally:
        auto_index_state.mark_finished()
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
    auto_index_state.mark_started()
    indexer = _Indexer(readiness_after=10_000)
    tool = _Tool()
    try:
        assert await tool._wait_for_first_chunks(indexer, poll_s=0.02) is False
    finally:
        auto_index_state.mark_finished()
    assert indexer.calls >= 2


@pytest.mark.asyncio
async def test_does_not_wait_when_indexing_never_started(monkeypatch):
    """Нет признака индексации → ждём только короткое окно появления, не бюджет."""
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "3")
    auto_index_state.mark_finished()
    indexer = _Indexer(readiness_after=10_000)
    tool = _Tool()

    started = time.monotonic()
    result = await tool._wait_for_first_chunks(indexer, poll_s=0.02)
    elapsed = time.monotonic() - started

    assert result is False
    assert elapsed < 1.3, f"ожидание впустую {elapsed:.2f} с — бюджет не соблюдён"


def test_empty_index_hint_distinguishes_building_from_not_started():
    """Совет обязан отличать «строится» от «не запускалась»."""

    class _Idx:
        project_path = "D:/proj"

    building = MCPTool._empty_index_hint(_Idx(), {"is_reindexing": True})
    idle = MCPTool._empty_index_hint(_Idx(), {})

    assert "being built" in building
    assert "progress" in building
    assert "no indexing was started" in idle
    assert "codebase(action='index'" in idle


@pytest.mark.asyncio
async def test_wait_does_not_block_event_loop(monkeypatch):
    """Тики считаются только внутри окна ожидания.

    Ревью 2026-11-16: считать тики после окончания ожидания нельзя — тикер
    продолжает работать и даёт одинаковое число в обоих случаях. Здесь тикер
    останавливается по завершении: `await asyncio.sleep(0.3)` → ~100 тиков,
    блокирующий `time.sleep(0.3)` → единицы.
    """
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "1.0")
    auto_index_state.mark_started()
    indexer = _Indexer(readiness_after=10_000)
    tool = _Tool()
    ticks = 0
    stop = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not stop.is_set():
            await asyncio.sleep(0.01)
            ticks += 1

    try:
        wait_task = asyncio.create_task(tool._wait_for_first_chunks(indexer, poll_s=0.3))
        tick_task = asyncio.create_task(ticker())
        await wait_task
        stop.set()
        await tick_task
    finally:
        auto_index_state.mark_finished()

    assert ticks >= 20, f"event loop блокировался: тиков {ticks} за 1 с ожидания"


# ══════════════════════════════════════════════════════════════════
# Проводка: require_ready_project действительно ждёт (ревью 2026-11-16)
# ══════════════════════════════════════════════════════════════════


class _Verdict:
    """Ответ RuntimeCoordinator.can_execute для готового проекта."""

    reason = "ready"
    state = "READY"
    detail = ""

    def __bool__(self) -> bool:
        return True


class _GrowingIndexer:
    """Индекс пуст первые N опросов, затем наполняется."""

    project_path = Path("D:/proj")

    def __init__(self, ready_after: int):
        self.calls = 0
        self.ready_after = ready_after

    def get_status(self):
        self.calls += 1
        return {"total_chunks": 10 if self.calls > self.ready_after else 0}


class _ReadyTool(MCPTool):
    """Минимальный инструмент: проверяем только ожидание индекса."""

    def __init__(self, indexer):
        self._services = None
        self.services = None
        self.tool_name = "wiring"
        self._indexer = indexer

    async def execute(self, **kwargs):  # pragma: no cover
        return ""

    def _resolve_target_path(self, explicit_project_root=None):
        return Path("D:/proj")

    def resolve_indexer(self, explicit_project_root=None):
        return self._indexer


@pytest.fixture()
def _coordinator_ready(monkeypatch):
    import src.core.lsp_project_bridge as bridge_mod
    import src.core.runtime_coordinator as rc_mod

    class _Coord:
        def __init__(self, services=None):
            pass

        async def can_execute(self, target, timeout=5.0):
            return _Verdict()

    monkeypatch.setattr(rc_mod, "RuntimeCoordinator", _Coord)
    monkeypatch.setattr(
        bridge_mod, "read_project_from_bridge", lambda max_wait=1.0: "D:/proj"
    )


@pytest.mark.asyncio
async def test_require_ready_project_waits_while_auto_index_runs(
    monkeypatch, _coordinator_ready
):
    """Индексация идёт → запрос ждёт первые чанки и не падает."""
    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "3")
    auto_index_state.mark_started()
    indexer = _GrowingIndexer(ready_after=2)
    try:
        await _ReadyTool(indexer).require_ready_project(explicit_project_root="D:/proj")
    finally:
        auto_index_state.mark_finished()

    assert indexer.calls >= 3, "ожидание должно было опросить статус несколько раз"


@pytest.mark.asyncio
async def test_require_ready_project_fails_fast_when_indexing_is_not_running(
    monkeypatch, _coordinator_ready
):
    """Индексация не идёт → отказ сразу с понятным советом, без 3 с ожидания."""
    from src.core.error_handler import IndexNotReadyError

    monkeypatch.setenv("MSCODEBASE_INDEX_WAIT_S", "3")
    auto_index_state.mark_finished()
    indexer = _GrowingIndexer(ready_after=10_000)
    tool = _ReadyTool(indexer)

    started = time.monotonic()
    with pytest.raises(IndexNotReadyError) as exc:
        await tool.require_ready_project(explicit_project_root="D:/proj")
    elapsed = time.monotonic() - started

    detail = str(getattr(exc.value, "detail", "") or exc.value)
    assert "Index is empty" in detail
    assert elapsed < 2.9, f"отказ должен быть быстрым, а не {elapsed:.1f} с"
