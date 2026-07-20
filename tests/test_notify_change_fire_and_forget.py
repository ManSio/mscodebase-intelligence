"""
Тесты: notify_change fire-and-forget (этап Б).

Покрывают (AGENTS.md §5.16 — не блокирует loop + отвечает без таймаута):
1. execute возвращает "Queued" сразу, НЕ дожидаясь re-embed файла.
2. Параллельный asyncio.sleep не задерживается (loop жив).
3. Фоновая индексация реально запускается (create_task вызван).
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.mcp.tools.indexing_tools import NotifyChangeTool
from src.core.di_container import ServiceCollection


def _make_tool(slow_index_seconds: float = 0.3):
    services = MagicMock(spec=ServiceCollection)
    indexer = MagicMock()
    indexer.searcher = None

    def _slow_index(*a, **k):
        import time
        time.sleep(slow_index_seconds)
        return True

    indexer._index_single_file.side_effect = _slow_index
    batch = MagicMock()
    batch.add = MagicMock(return_value=asyncio.sleep(0, result=True))
    indexer.bm25_batch = batch

    tool = NotifyChangeTool(services)
    tool.resolve_indexer = MagicMock(return_value=indexer)
    tool._get_project_root = MagicMock(return_value=__import__("pathlib").Path(".").resolve())
    tool.rate_limiter.acquire.return_value = True
    tool._project_header = MagicMock(return_value="")
    return tool, indexer


async def test_notify_change_returns_queued_immediately():
    """execute возвращает 'Queued' сразу, не дожидаясь slow _index_single_file."""
    tool, indexer = _make_tool(slow_index_seconds=0.3)

    async def _fake_content(*a, **k):
        return ("print('x')", "filesystem")

    tool._resolve_and_validate_path = MagicMock(
        return_value=__import__("pathlib").Path("src/core/search/engine.py").resolve()
    )
    tool._get_content = _fake_content

    async def _parallel_sleep():
        t0 = asyncio.get_event_loop().time()
        await asyncio.sleep(0.05)
        return asyncio.get_event_loop().time() - t0

    sleep_task = asyncio.create_task(_parallel_sleep())
    exec_task = asyncio.create_task(tool.execute(file_path="src/core/search/engine.py"))
    sleep_elapsed, result = await asyncio.gather(sleep_task, exec_task)

    # sleep не заблокирован
    assert sleep_elapsed < 0.2, f"loop blocked: {sleep_elapsed:.2f}s"
    # ответ сразу "Queued", не дожидаясь индексации (0.3s)
    assert "Queued" in result
    # фоновая задача запущена (create_task вызван внутри execute)
    assert asyncio.all_tasks()  # есть активные задачи (фоновая индексация)


async def test_notify_change_background_index_runs():
    """Фоновая индексация реально выполняется (не просто пропущена)."""
    tool, indexer = _make_tool(slow_index_seconds=0.1)
    tool._resolve_and_validate_path = MagicMock(
        return_value=__import__("pathlib").Path("src/core/search/engine.py").resolve()
    )

    async def _fake_content(*a, **k):
        return ("print('x')", "filesystem")

    tool._get_content = _fake_content

    result = await tool.execute(file_path="src/core/search/engine.py")
    assert "Queued" in result
    # Даём фоновой задаче отработать
    await asyncio.sleep(0.3)
    assert indexer._index_single_file.called, "фоновая индексация не запустилась"
