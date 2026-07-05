"""
Task Queue — фоновая очередь задач для MCP.

Решает проблему долгих синхронных вызовов:
- Анализ коммитов (Bug Correlation)
- Построение графа знаний (Relation Extraction)
- Тяжёлые вычисления

Принцип:
1. MCP tool ставит задачу в очередь
2. Сразу возвращает {task_id, status: "queued"}
3. Фоновый воркер выполняет задачу
4. Результат сохраняется в _task_results
5. Клиент опрашивает get_task_result(task_id)
"""

import asyncio
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("task_queue")


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """Фоновая задача."""

    id: str
    name: str
    func: Callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.QUEUED
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    progress: float = 0.0  # 0.0 - 1.0


class TaskQueue:
    """Универсальная очередь фоновых задач."""

    def __init__(self, max_workers: int = 2):
        self._queue: asyncio.Queue = None
        self._results: Dict[str, Task] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._worker_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self):
        """Запускает фоновый воркер."""
        self._queue = asyncio.Queue()
        self._loop = asyncio.get_event_loop()
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("TaskQueue запущена")

    async def stop(self):
        """Останавливает воркер."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._executor.shutdown(wait=False)
        logger.info("TaskQueue остановлена")

    def submit_sync(
        self,
        name: str,
        func: Callable,
        *args,
        **kwargs,
    ) -> str:
        """Синхронно ставит задачу в очередь (для вызова из sync кода).

        Args:
            name: Человекочитаемое имя задачи
            func: Функция для выполнения
            *args, **kwargs: Аргументы функции

        Returns:
            task_id для отслеживания
        """
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            id=task_id,
            name=name,
            func=func,
            args=args,
            kwargs=kwargs,
        )
        self._results[task_id] = task

        # Пытаемся положить в очередь (создаём если нет)
        try:
            if self._queue is None:
                self._queue = asyncio.Queue()
            # Используем run_coroutine_threadsafe для потокобезопасности
            loop = self._loop or asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(self._queue.put(task), loop)
        except RuntimeError:
            # Нет event loop — задача в очереди на следующий старт
            pass

        logger.info(f"Задача поставлена в очередь: {name} [{task_id}]")
        return task_id

    async def submit(
        self,
        name: str,
        func: Callable,
        *args,
        **kwargs,
    ) -> str:
        """Асинхронно ставит задачу в очередь.

        Args:
            name: Человекочитаемое имя задачи
            func: Функция для выполнения
            *args, **kwargs: Аргументы функции

        Returns:
            task_id для отслеживания
        """
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            id=task_id,
            name=name,
            func=func,
            args=args,
            kwargs=kwargs,
        )
        self._results[task_id] = task
        await self._queue.put(task)
        logger.info(f"Задача поставлена в очередь: {name} [{task_id}]")
        return task_id

    def get_status(self, task_id: str) -> Optional[Dict]:
        """Возвращает статус задачи."""
        task = self._results.get(task_id)
        if not task:
            return None

        return {
            "id": task.id,
            "name": task.name,
            "status": task.status.value,
            "progress": task.progress,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "result": task.result if task.status == TaskStatus.COMPLETED else None,
            "error": task.error,
        }

    def get_result(self, task_id: str) -> Optional[Any]:
        """Возвращает результат выполненной задачи."""
        task = self._results.get(task_id)
        if not task or task.status != TaskStatus.COMPLETED:
            return None
        return task.result

    async def _worker_loop(self):
        """Основной цикл воркера."""
        while True:
            try:
                task = await self._queue.get()
                await self._execute_task(task)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка воркера: {e}")

    async def _execute_task(self, task: Task):
        """Выполняет задачу в пуле потоков."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now().isoformat()
        task.progress = 0.1

        try:
            # Запускаем синхронную функцию в пуле потоков
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self._executor,
                self._run_sync_task,
                task,
            )
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.progress = 1.0
            logger.info(f"Задача завершена: {task.name} [{task.id}]")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"Задача упала: {task.name} [{task.id}]: {e}")

        finally:
            task.completed_at = datetime.now().isoformat()

    def _run_sync_task(self, task: Task):
        """Обёртка для выполнения синхронной задачи."""
        # Добавляем progress callback если функция поддерживает
        if "progress_callback" in task.func.__code__.co_varnames:
            task.kwargs["progress_callback"] = lambda p: setattr(task, "progress", p)
        return task.func(*task.args, **task.kwargs)

    def cleanup_old_results(self, max_age_minutes: int = 30):
        """Очищает старые результаты."""
        now = datetime.now()
        to_remove = []
        for task_id, task in self._results.items():
            if task.completed_at:
                try:
                    completed = datetime.fromisoformat(task.completed_at)
                    age = (now - completed).total_seconds() / 60
                    if age > max_age_minutes:
                        to_remove.append(task_id)
                except (ValueError, TypeError):
                    pass

        for task_id in to_remove:
            del self._results[task_id]


# Глобальный инстанс
_task_queue = TaskQueue(max_workers=2)


def get_task_queue() -> TaskQueue:
    """Возвращает глобальный TaskQueue."""
    return _task_queue


# ══════════════════════════════════════════════════════════
# IdleScheduler — фоновые задачи в простое
# ══════════════════════════════════════════════════════════

_IDLE_SCHEDULER_ENABLED: bool = False
_LAST_IDLE_TASK_AT: float = 0.0
_IDLE_COOLDOWN_SEC: int = 120  # не чаще раза в 2 минуты


def enable_idle_scheduler():
    """Включает IdleScheduler (вызывается из server.py после инициализации)."""
    global _IDLE_SCHEDULER_ENABLED
    _IDLE_SCHEDULER_ENABLED = True


def disable_idle_scheduler():
    """Выключает IdleScheduler."""
    global _IDLE_SCHEDULER_ENABLED
    _IDLE_SCHEDULER_ENABLED = False


def _cpu_available() -> bool:
    """Проверяет, можно ли запустить фоновую задачу по ресурсам."""
    try:
        from src.core.resource_monitor import get_global_resource_monitor

        mon = get_global_resource_monitor()
        return not mon.is_under_pressure() if mon else True
    except Exception:
        return True


def _improve_summaries_batch(batch_size: int = 2):
    """Улучшает summaries для чанков без них (Preemptible)."""
    import json
    import random

    # Заглушка — реальная логика подключится через DI
    logger.debug(f"[Idle] improve_summaries batch={batch_size}")


def _check_index_health():
    """Проверка целостности индекса (preemptible)."""
    logger.debug("[Idle] check_index_health")


def idle_tick():
    """Вызывается из record_tool_call() после каждого инструмента.

    Планирует фоновые задачи в зависимости от времени простоя.
    """
    global _LAST_IDLE_TASK_AT

    if not _IDLE_SCHEDULER_ENABLED:
        return

    # Не чаще раза в 2 минуты
    if time.time() - _LAST_IDLE_TASK_AT < _IDLE_COOLDOWN_SEC:
        return

    # Проверяем ресурсы
    if not _cpu_available():
        return

    queue = get_task_queue()
    now = time.time()

    # Берём idle_ms из _LAST_CALL_AT в error_handler
    try:
        from src.core.error_handler import _LAST_CALL_AT

        idle_sec = now - _LAST_CALL_AT
    except Exception:
        idle_sec = 0

    # Уровень 1: >5s простоя — быстрые задачи
    if idle_sec > 5:
        queue.submit_sync("check_index_health", _check_index_health)
        _LAST_IDLE_TASK_AT = now

    # Уровень 2: >30s простоя — улучшение summaries (маленькими батчами)
    if idle_sec > 30:
        queue.submit_sync("improve_summaries", _improve_summaries_batch, 2)

    logger.info(
        f"[Idle] Scheduled background tasks (idle={idle_sec:.0f}s, "
        f"cpu={'ok' if _cpu_available() else 'busy'})"
    )
