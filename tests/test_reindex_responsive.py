"""Регрессия: reindex (включая авто-обновление документации) НЕ блокирует event loop.

Инцидент 2026-08-13: updater.update_all() вызывался синхронно в main loop →
все MCP-запросы таймаутили ~13 мин, Zed убил MCP-процесс.
Фикс: asyncio.to_thread + wait_for(300) — BS-11-класс (как run_full_diagnostic
в intel_predict_root_cause).

Тест: пока update_all "спит" 0.4с в executor-потоке, event loop обязан тикать
с нормальным интервалом. Если бы update_all остался в main loop — тики
замерли бы на >= 0.4с и тест упал бы.
"""

import asyncio
import time

import pytest

from src.core.intelligence.jobs import job_manager
from src.core.intelligence.layer import ProjectIntelligenceLayer


@pytest.fixture
def project(tmp_path):
    """Минимальный изолированный проект (data_root изолируется conftest)."""
    proj = tmp_path / "project"
    proj.mkdir()
    (proj / "src").mkdir()
    return proj


class _FakeDBM:
    def set_reindexing(self):
        pass

    def clear_reindexing(self):
        pass

    def is_reindexing(self):
        return False


class _FakeIndexer:
    """Быстрая индексация (мгновенно), db_manager с reindex-guard."""

    def __init__(self):
        self.db_manager = _FakeDBM()
        self.file_guard = None
        self.index_project_calls = 0

    def index_project(self, path, progress_callback=None):
        self.index_project_calls += 1
        return 1


class _SlowDocUpdater:
    """Синхронный тяжёлый updater: в main loop заблокировал бы event loop."""

    def update_all(self, project_root: str) -> str:
        time.sleep(0.4)  # тяжёлая sync-работа
        return "ok"


async def test_reindex_autodoc_does_not_block_event_loop(project, monkeypatch):
    layer = ProjectIntelligenceLayer(project, _FakeIndexer(), None, None)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "src.core.auto_doc_updater.AutoDocUpdater", _SlowDocUpdater
    )

    tick_times: list[float] = []

    async def ticker():
        for _ in range(10):
            await asyncio.sleep(0.05)
            tick_times.append(time.monotonic())

    tick_task = asyncio.create_task(ticker())
    job_id = await layer.trigger_async_reindex()

    # Ждём завершения job'а (индексация мгновенная, update_all 0.4s)
    for _ in range(80):
        job = job_manager.get_job(job_id)
        if job and job.status == "completed":
            break
        await asyncio.sleep(0.05)
    await tick_task

    job = job_manager.get_job(job_id)
    assert job is not None
    assert job.status == "completed", f"job.status={job.status}"

    # Главный критерий: event loop НЕ замирал — макс. интервал между тиками < 0.3с.
    # (при sync-update_all в main loop тики замерли бы на ~0.4с и тест упал бы)
    assert len(tick_times) == 10, f"тиков {len(tick_times)}"
    gaps = [b - a for a, b in zip(tick_times, tick_times[1:])]
    max_gap = max(gaps) if gaps else 0.0
    assert max_gap < 0.3, (
        f"event loop замер на {max_gap:.2f}s — sync-блокировка в main loop"
    )


def test_search_fast_fail_during_reindex():
    """Reindex guard: все пути поиска мгновенно возвращают пусто при
    is_reindexing=True (инцидент 2026-08-13: search_code таймаутил на lock'ах
    БД/FTS5 во время full reindex)."""
    from types import SimpleNamespace

    from src.core.search.engine import Searcher

    idx = SimpleNamespace(db_manager=SimpleNamespace(is_reindexing=lambda: True))
    searcher = Searcher(idx, None)  # type: ignore[arg-type]

    assert searcher._reindex_fast_fail() is True
    out = searcher.search_with_mode("query", mode="fast")
    assert out["results"] == []
    assert searcher.context_search("code fragment") == ""

    # Контроль: при is_reindexing=False guard выключен (обычный путь)
    idx.db_manager = SimpleNamespace(is_reindexing=lambda: False)
    assert searcher._reindex_fast_fail() is False


def test_get_status_fast_fail_during_reindex_does_not_block():
    """Инцидент 2026-08-25 (root cause): full reindex держит _table_write_lock
    ~7.5 мин (begin_write), а get_status() на loop-потоке ждал этот lock →
    заморожен ВСЕ MCP-вызовы. Теперь: reindex_check=True → get_status()
    возвращает кэш мгновенно, не трогая lock/БД.

    Двухрукавность (правило Тома):
    - Arm 1 (reindex_check=True): возврат быстрый (< 0.3с) при ЗАХВАЧЕННОМ lock.
    - Arm 2 (reindex_check=None): тот же lock → блокируется на acquire
      (>= 0.4с пока lock держит фоновый поток) — демонстрирует, что БЕЗ
      guard был именно lock-wait, а guard реально умеет падать/спасать.
    """
    import threading
    import time
    from pathlib import Path

    from src.core.indexing.index_status import IndexStatusReporter

    lock = threading.RLock()
    lock.acquire()  # держим lock, как begin_write() во время reindex
    try:
        reporter = IndexStatusReporter(
            table=None,
            project_path=Path("unused"),
            file_guard=None,
            watchdog_callback=None,
            table_write_lock=lock,
            reindex_check=lambda: True,
        )
        reporter._cached_total_chunks = 42
        reporter._cached_unique_files = {"a.py", "b.py"}

        t0 = time.perf_counter()
        status = reporter.get_status()
        dt = time.perf_counter() - t0

        # Fast-fail: не ждём lock, отдаём кэш + флаг reindex в статусе
        assert dt < 0.3, f"get_status заблокировался на {dt*1000:.0f}ms"
        assert status["total_chunks"] == 42
        assert status["unique_files"] == 2
        assert status["status"] == "reindexing"
        assert status["reindex_in_progress"] is True
    finally:
        lock.release()

    # Arm 2 (контроль): без reindex_check тот же lock блокирует get_status
    import threading as _th
    import time as _time

    lock2 = _th.RLock()
    lock2.acquire()
    try:
        reporter2 = IndexStatusReporter(
            table=None,
            project_path=Path("unused"),
            file_guard=None,
            watchdog_callback=None,
            table_write_lock=lock2,
            reindex_check=None,  # старый путь — lock-wait
        )
        t0 = _time.perf_counter()
        # Воркер в ОТДЕЛЬНОМ потоке: main держит lock, чужой поток обязан
        # ждать acquire — это и есть заморозка loop-потока в инциденте.
        result: dict = {}

        def _worker():
            result["status"] = reporter2.get_status()
            result["dt"] = _time.perf_counter() - t0

        _th.Thread(target=_worker, daemon=True).start()
        _time.sleep(0.2)
        # Через 0.2с воркер всё ещё ждёт lock → блокировка подтверждена
        assert "status" not in result, \
            "Без reindex_check get_status НЕ должен вернуться, пока lock занят"
        lock2.release()  # освобождаем → воркер проходит acquire и завершается
        _time.sleep(0.3)  # дать воркеру пройти get_status (lock уже свободен)
        assert "status" in result, "Воркер не завершился после release"
        assert result["dt"] >= 0.2, \
            "Контроль: lock-wait обязан был занять >=0.2с"
    finally:
        try:
            lock2.release()
        except RuntimeError:
            pass
