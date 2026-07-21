"""
Тест: NotifyChangeTool.execute НЕ блокирует event loop (AGENTS.md §5.16).

Раньше execute вызывал indexer._index_single_file() синхронно -> embed (ONNX)
и LanceDB write блокировали loop -> транспортный таймаут Zed
('Context server request timeout'). Фикс: вызов обёрнут в asyncio.to_thread.

Проверяем: параллельный asyncio.sleep(0.05) не задерживается, пока execute
"индексирует" (мок с искусственной задержкой).
"""
import asyncio
from unittest.mock import MagicMock

from src.core.di_container import ServiceCollection
from src.mcp.tools.indexing_tools import NotifyChangeTool


def _make_tool(slow_index_seconds: float = 0.3):
    """NotifyChangeTool с моком indexer, чей _index_single_file 'тормозит'."""
    services = MagicMock(spec=ServiceCollection)
    # resolve_indexer возвращает мок indexer
    indexer = MagicMock()
    indexer.searcher = None

    def _slow_index(*a, **k):
        # имитируем блокирующий embed+LanceDB write
        import time
        time.sleep(slow_index_seconds)
        return True

    indexer._index_single_file.side_effect = _slow_index
    # bm25_batch с async add (как DebounceBatch)
    batch = MagicMock()
    batch.add = MagicMock(return_value=asyncio.sleep(0, result=True))
    indexer.bm25_batch = batch
    tool = NotifyChangeTool(services)
    tool.resolve_indexer = MagicMock(return_value=indexer)
    tool._get_project_root = MagicMock(return_value=__import__("pathlib").Path(".").resolve())
    tool.rate_limiter.acquire.return_value = True
    tool._project_header = MagicMock(return_value="")
    return tool, indexer


async def test_notify_change_does_not_block_event_loop():
    """Параллельный sleep не должен ждать завершения 'индексации'."""
    tool, indexer = _make_tool(slow_index_seconds=0.3)

    # Мокаем _resolve_and_validate_path и _get_content, чтобы не трогать диск
    tool._resolve_and_validate_path = MagicMock(
        return_value=__import__("pathlib").Path("src/core/search/engine.py").resolve()
    )
    async def _fake_content(*a, **k):
        return ("print('x')", "filesystem")
    tool._get_content = _fake_content

    async def _parallel_sleep():
        t0 = asyncio.get_event_loop().time()
        await asyncio.sleep(0.05)
        return asyncio.get_event_loop().time() - t0

    # Запускаем execute и параллельный sleep одновременно
    sleep_task = asyncio.create_task(_parallel_sleep())
    exec_task = asyncio.create_task(
        tool.execute(file_path="src/core/search/engine.py")
    )
    sleep_elapsed, exec_result = await asyncio.gather(sleep_task, exec_task)

    # sleep не должен быть заблокирован тормозящим indexer (допуск x3)
    assert sleep_elapsed < 0.2, f"event loop blocked: sleep took {sleep_elapsed:.2f}s"
    assert "Queued for reindex" in exec_result


async def test_notify_change_uses_to_thread():
    """_index_single_file вызывается (через to_thread) ровно один раз."""
    tool, indexer = _make_tool(slow_index_seconds=0.0)
    tool._resolve_and_validate_path = MagicMock(
        return_value=__import__("pathlib").Path("src/core/search/engine.py").resolve()
    )
    async def _fake_content(*a, **k):
        return ("print('x')", "filesystem")
    tool._get_content = _fake_content

    result = await tool.execute(file_path="src/core/search/engine.py")
    # _index_single_file вызывается в fire-and-forget task (create_task).
    # Ждём немного чтобы background task успел стартануть
    await asyncio.sleep(0.05)
    assert indexer._index_single_file.call_count == 1
    assert "Queued for reindex" in result
