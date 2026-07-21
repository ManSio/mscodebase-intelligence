"""
Тесты для Task Queue — фоновая очередь задач.
"""

import asyncio
import time

import pytest

from src.core.task_queue import TaskQueue, TaskStatus


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
