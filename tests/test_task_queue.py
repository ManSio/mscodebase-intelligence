"""
Тесты для Task Queue — фоновая очередь задач.
"""

import asyncio
import threading
import time

import pytest

from src.core.task_queue import TaskQueue, TaskStatus


def _raise_no_loop(coro, loop):
    """Эмуляция отсутствия работающего event loop (RuntimeError)."""
    raise RuntimeError("no event loop")


class _FakeQueue:
    """Минимальная очередь для sync-тестов (put без реального loop)."""

    def put(self, task):
        return None


class TestTaskQueue:
    """Тесты TaskQueue."""

    @pytest.mark.asyncio
    async def test_submit_and_complete(self):
        """Задача выполняется и возвращает результат."""
        queue = TaskQueue(max_workers=1)
        await queue.start()

        def simple_task():
            return "done"

        task_id = await queue.submit("test", simple_task)
        assert task_id is not None

        # Ждём завершения
        for _ in range(50):
            status = queue.get_status(task_id)
            if status["status"] == "completed":
                break
            await asyncio.sleep(0.1)

        result = queue.get_result(task_id)
        assert result == "done"

        await queue.stop()

    @pytest.mark.asyncio
    async def test_task_failure(self):
        """Упавшая задача возвращает ошибку."""
        queue = TaskQueue(max_workers=1)
        await queue.start()

        def failing_task():
            raise ValueError("test error")

        task_id = await queue.submit("failing", failing_task)

        # Ждём завершения
        for _ in range(50):
            status = queue.get_status(task_id)
            if status["status"] == "failed":
                break
            await asyncio.sleep(0.1)

        status = queue.get_status(task_id)
        assert status["status"] == "failed"
        assert "test error" in status["error"]

        await queue.stop()

    @pytest.mark.asyncio
    async def test_multiple_tasks(self):
        """Несколько задач выполняются параллельно."""
        queue = TaskQueue(max_workers=2)
        await queue.start()

        def slow_task(duration):
            time.sleep(duration)
            return f"slept {duration}"

        id1 = await queue.submit("task1", slow_task, 0.1)
        id2 = await queue.submit("task2", slow_task, 0.1)

        # Ждём завершения обеих
        for _ in range(100):
            s1 = queue.get_status(id1)
            s2 = queue.get_status(id2)
            if s1["status"] == "completed" and s2["status"] == "completed":
                break
            await asyncio.sleep(0.1)

        assert queue.get_result(id1) == "slept 0.1"
        assert queue.get_result(id2) == "slept 0.1"

        await queue.stop()

    @pytest.mark.asyncio
    async def test_get_status_not_found(self):
        """Несуществующая задача возвращает None."""
        queue = TaskQueue()
        assert queue.get_status("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_result_not_completed(self):
        """Результат невозможно получить до завершения."""
        queue = TaskQueue(max_workers=1)
        await queue.start()

        def slow_task():
            time.sleep(1)
            return "done"

        task_id = await queue.submit("slow", slow_task)
        # Сразу после отправки результата нет
        assert queue.get_result(task_id) is None

        await queue.stop()

    def test_cleanup_old_results(self):
        """Очистка старых результатов."""
        queue = TaskQueue()
        # Добавляем старый результат вручную
        from src.core.task_queue import Task
        old_task = Task(
            id="old1",
            name="old",
            func=lambda: None,
            status=TaskStatus.COMPLETED,
        )
        old_task.completed_at = "2020-01-01T00:00:00"
        queue._results["old1"] = old_task

        queue.cleanup_old_results(max_age_minutes=1)
        assert "old1" not in queue._results

    def test_submit_sync_failure_cleanup(self, monkeypatch):
        """RuntimeError при постановке → задача НЕ «застревает» в регистрации.

        Регрессия deep-research-report.md P1: except RuntimeError: pass оставлял
        задачу в _pending_names/_results навсегда — повторный submit с тем же
        именем возвращал None вечно, а лог «поставлена в очередь» врал.
        """
        queue = TaskQueue(max_workers=1)
        monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _raise_no_loop)

        task_id = queue.submit_sync("foo", lambda: "ok")

        assert task_id is None
        assert "foo" not in queue._pending_names, "Задача не должна остаться в pending_names"
        assert queue._results == {}, "Задача не должна остаться в _results"
        assert queue.has_pending("foo") is False

    def test_submit_sync_dedup_concurrent(self, monkeypatch):
        """Гонка двух потоков на submit_sync: ровно одна задача получает task_id.

        Без lock (check-then-add) оба потока могли пройти проверку и создать
        две задачи с одним именем. С _submit_lock — ровно один победитель.
        """
        queue = TaskQueue(max_workers=1)
        monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", lambda coro, loop: None)
        loop = asyncio.new_event_loop()
        queue._loop = loop
        queue._queue = _FakeQueue()  # не None — пропускаем создание asyncio.Queue

        try:
            barrier = threading.Barrier(2)
            results = []
            results_lock = threading.Lock()

            def worker():
                barrier.wait()
                tid = queue.submit_sync("foo", lambda: "ok")
                with results_lock:
                    results.append(tid)

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            loop.close()

        granted = [tid for tid in results if tid is not None]
        assert len(granted) == 1, f"Ожидался 1 task_id, получено {len(granted)}: {results}"
        assert queue.has_pending("foo") is True
