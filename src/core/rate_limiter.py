"""Защита от перегрузки: Rate Limiting + Circuit Breaker.

Предотвращает:
- Бесконечные циклы notify_change при рекурсивном рефакторинге
- DDoS LSP VFS через массовые вызовы инструментов
- Перегрузку LM Studio при массовой индексации

ИСПРАВЛЕНО (v2):
- Добавлен asyncio.Lock() для потокобезопасности SlidingWindowRateLimiter
- Добавлен DebounceBatch для notify_change (не реиндексирует BM25 на каждый файл)
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Set

__all__ = [
    "SlidingWindowRateLimiter",
    "DebounceConfig",
    "DebounceBatch",
    "CircuitBreaker",
]
logger = logging.getLogger("mscodebase_server.rate_limiter")


# ══════════════════════════════════════════════════════════
# Sliding Window Rate Limiter
# ══════════════════════════════════════════════════════════


class SlidingWindowRateLimiter:
    """Sliding Window Rate Limiter с threading.Lock для потокобезопасности.

    Позволяет: 10 вызовов/сек для notify_change, 30/сек для поиска, 1/сек для git.

    Защита от race conditions: threading.Lock (НЕ asyncio.Lock) —
    см. INC-53EC / REFC-03. Lock шарится между event-loop-ами LSP и MCP,
    asyncio.Lock привязывается к loop-у первого await и дедлочит.
    """

    def __init__(self):
        self._windows: Dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()  # см. INC-53EC / REFC-03

    def acquire(self, key: str, max_per_sec: float = 10.0) -> bool:
        """Пытается захватить слот. Возвращает False если превышен лимит.

        Потокобезопасен: использует threading.Lock. Совместим с sync- и
        async-вызывающими (async просто делает `await asyncio.to_thread`).
        """
        with self._lock:
            now = time.monotonic()
            window = self._windows[key]

            # Очищаем старые записи (старше 1 секунды)
            cutoff = now - 1.0
            self._windows[key] = [t for t in window if t > cutoff]

            if len(self._windows[key]) >= max_per_sec:
                logger.debug(
                    f"Rate limit exceeded for '{key}': "
                    f"{len(self._windows[key])} req/sec (limit: {max_per_sec})"
                )
                return False

            self._windows[key].append(now)
            return True

    async def acquire_async(self, key: str, max_per_sec: float = 10.0) -> bool:
        """Async-обёртка над acquire() — не блокирует event loop."""
        return await asyncio.to_thread(self.acquire, key, max_per_sec)

    async def wait_or_skip(
        self, key: str, max_per_sec: float = 10.0, max_wait_ms: int = 100
    ) -> bool:
        """Ждет до max_wait_ms, если лимит превышен — возвращает False (skip).

        Позволяет избежать блокировки агента: вместо долгого ожидания
        возвращает управление с рекомендацией повторить позже.
        """
        wait_step = max_wait_ms / 10  # 10 попыток
        for _ in range(10):
            if await self.acquire_async(key, max_per_sec):
                return True
            await asyncio.sleep(wait_step / 1000)

        logger.warning(f"Rate limit: '{key}' skipped after {max_wait_ms}ms wait")
        return False

    def get_stats(self, key: str) -> dict:
        """Возвращает текущую статистику для ключа."""
        with self._lock:
            window = self._windows.get(key, [])
            now = time.monotonic()
            recent = [t for t in window if t > now - 1.0]
            return {
                "key": key,
                "requests_last_sec": len(recent),
                "total_tracked": len(window),
            }


# ══════════════════════════════════════════════════════════
# Debounce Batch Queue — для пакетной реиндексации BM25
# ══════════════════════════════════════════════════════════


@dataclass
class DebounceConfig:
    """Конфигурация Debounce механизма."""

    debounce_ms: int = 500  # Ждем 500ms после последнего события
    max_batch_size: int = 100  # Максимальный размер батча
    max_wait_ms: int = 5000  # Максимальное время ожидания (защита от зависания)


class DebounceBatch:
    """Пакетная обработка с debounce — для notify_change + BM25 реиндексации.

    Вместо того чтобы перестраивать BM25 индекс после каждого _index_single_file,
    накапливаем изменённые файлы в Set и сбрасываем через debounce.

    Пример использования:
        batch = DebounceBatch(
            callback=lambda files: searcher.reindex(),
            config=DebounceConfig(debounce_ms=500)
        )
        await batch.add(path)

    Lock: asyncio.Lock — защищает set/files от конкурентных add() из разных task-ов.
    Таймер работает в loop-е, в котором был создан; callback выполняется через
    asyncio.to_thread() если sync, или await если async.
    """

    def __init__(
        self,
        callback: Callable[[Set[str]], None],
        config: Optional[DebounceConfig] = None,
    ):
        self._callback = callback
        self._config = config or DebounceConfig()
        self._files: Set[str] = set()
        self._timer: Optional[asyncio.Task] = None
        self._last_added_at = 0.0
        self._lock = asyncio.Lock()  # asyncio.Lock для корректной работы в event loop

    async def add(self, file_path: str) -> bool:
        """Добавляет файл в батч. Возвращает True если файл новый."""
        async with self._lock:
            is_new = file_path not in self._files
            self._files.add(file_path)
            self._last_added_at = time.monotonic()
            batch_full = len(self._files) >= self._config.max_batch_size
            timer_missing = self._timer is None or self._timer.done()

        if batch_full:
            logger.info("Batch full, flushing immediately")
            await self._flush()
            return is_new

        if timer_missing:
            self._timer = asyncio.create_task(self._debounce_wait())
            logger.debug(f"Debounce timer started ({self._config.debounce_ms}ms)")

        return is_new

    async def _debounce_wait(self):
        """Ждет debounce_ms после последнего события, затем сбрасывает батч.

        Защита от зависания: если файлы добавляются непрерывно > max_wait_ms,
        сбрасываем принудительно.

        ВАЖНО: НЕ вызывать await внутри with self._lock — asyncio.Lock
        не блокирует поток, но _flush() также захватывает этот lock.
        Правильный паттерн: решение о flush под lock, сам flush — вне lock.
        """
        try:
            while True:
                await asyncio.sleep(self._config.debounce_ms / 1000)

                # Решение о flush принимаем под lock, но сам flush — вне lock
                should_flush = False
                should_exit = False

                async with self._lock:
                    elapsed = time.monotonic() - self._last_added_at
                    elapsed_ms = elapsed * 1000
                    has_files = bool(self._files)

                    if elapsed_ms >= self._config.debounce_ms:
                        should_flush = has_files
                        should_exit = True
                    elif elapsed >= self._config.max_wait_ms / 1000:
                        logger.warning(f"Forced flush after {elapsed:.0f}s")
                        should_flush = has_files
                        should_exit = True

                # Lock отпущен — безопасно делать await
                if should_flush:
                    await self._flush()
                if should_exit:
                    return

        except asyncio.CancelledError:
            logger.debug("Debounce timer cancelled, new timer will handle batch")
        except Exception as e:
            logger.error(f"Debounce timer error: {e}")

    async def _flush(self):
        """Сбрасывает накопленные файлы в callback."""
        async with self._lock:
            if not self._files:
                return
            files = self._files.copy()
            self._files.clear()
            self._timer = None

        logger.info(f"Debounce flushing {len(files)} files to callback")
        try:
            # callback может быть sync или async — поддерживаем оба.
            result = self._callback(files)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Debounce callback error: {e}")

    async def flush_now(self):
        """Принудительный сброс (для graceful shutdown)."""
        async with self._lock:
            timer = self._timer
        if timer and not timer.done():
            timer.cancel()
        await self._flush()

    async def pending_count(self) -> int:
        async with self._lock:
            return len(self._files)


# ══════════════════════════════════════════════════════════
# Circuit Breaker — защита от каскадных сбоев
# ══════════════════════════════════════════════════════════


class CircuitBreaker:
    """Circuit Breaker для предотвращения каскадных сбоев.

    Состояния: CLOSED (работает) → OPEN (отказ) → HALF_OPEN (тест).

    Example:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        result = await cb.call(
            lambda: lm_studio_request(),
            fallback={"status": "fallback", "message": "LM Studio unavailable"}
        )
    """

    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "default",
        on_state_change: Optional[Callable[[str, str, Optional[str]], None]] = None,
    ):
        """
        Args:
            on_state_change: Опциональный callback при смене состояния.
                Сигнатура: (old_state, new_state, error_message)
        """
        self.name = name
        self.state = self.STATE_CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = 0.0
        self.last_state_change = time.monotonic()
        self._lock = asyncio.Lock()  # asyncio.Lock для корректной работы в event loop
        self._on_state_change = on_state_change
        self._last_error: Optional[str] = None

    async def _notify_state_change(self, old_state: str, new_state: str):
        """Уведомляет о смене состояния через callback."""
        if self._on_state_change:
            try:
                self._on_state_change(
                    old_state,
                    new_state,
                    self._last_error,
                )
            except Exception as _e:
                logger.warning("exception", exc_info=True)
                pass
    async def call(self, coro_factory: Callable, fallback: Any = None) -> Any:
        """Выполняет корутину через circuit breaker.

        Args:
            coro_factory: Асинхронная функция без аргументов
            fallback: Значение, возвращаемое при OPEN состоянии
        """
        # Проверка: можно ли пробовать?
        old_state = self.state
        async with self._lock:
            if self.state == self.STATE_OPEN:
                if time.monotonic() - self.last_failure_time > self.recovery_timeout:
                    logger.info(
                        f"Circuit breaker [{self.name}]: OPEN → HALF_OPEN "
                        f"(recovery timeout reached)"
                    )
                    self.state = self.STATE_HALF_OPEN
                    self.last_state_change = time.monotonic()
                else:
                    remaining = self.recovery_timeout - (
                        time.monotonic() - self.last_failure_time
                    )
                    logger.debug(
                        f"Circuit breaker [{self.name}]: OPEN, "
                        f"bypassing call ({remaining:.0f}s remaining)"
                    )
                    return fallback

        if self.state != old_state:
            await self._notify_state_change(old_state, self.state)

        # Выполняем вызов
        old_state = self.state
        try:
            result = await coro_factory()

            async with self._lock:
                if self.state == self.STATE_HALF_OPEN:
                    logger.info(
                        f"Circuit breaker [{self.name}]: HALF_OPEN → CLOSED "
                        f"(test request succeeded)"
                    )
                    self.state = self.STATE_CLOSED
                    self.last_state_change = time.monotonic()
                self.failure_count = 0
                self.success_count += 1

            if self.state != old_state:
                await self._notify_state_change(old_state, self.state)

            return result

        except Exception as e:
            self._last_error = str(e)
            async with self._lock:
                self.failure_count += 1
                self.success_count = 0
                self.last_failure_time = time.monotonic()

                if self.failure_count >= self.failure_threshold:
                    old = self.state
                    logger.error(
                        f"Circuit breaker [{self.name}]: → OPEN "
                        f"({self.failure_count} consecutive failures): {e}"
                    )
                    self.state = self.STATE_OPEN
                    self.last_state_change = time.monotonic()

                    if self.state != old:
                        await self._notify_state_change(old, self.state)

            if fallback is not None:
                return fallback
            raise

    def get_state(self) -> dict:
        """Возвращает состояние circuit breaker."""
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_sec_ago": (
                time.monotonic() - self.last_failure_time
                if self.last_failure_time > 0
                else None
            ),
        }
