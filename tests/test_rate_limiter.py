"""Unit-тесты для rate_limiter.py: SlidingWindowRateLimiter, DebounceBatch, CircuitBreaker."""

from __future__ import annotations

import asyncio

import pytest

from src.core.rate_limiter import (
    CircuitBreaker,
    DebounceBatch,
    DebounceConfig,
    SlidingWindowRateLimiter,
)

# ══════════════════════════════════════════════════════════
# SlidingWindowRateLimiter
# ══════════════════════════════════════════════════════════

class TestSlidingWindowRateLimiter:
    """Sliding Window Rate Limiter с asyncio.Lock."""

    @pytest.mark.asyncio
    async def test_acquire_within_limit(self):
        """acquire_async возвращает True если лимит не превышен.

        (См. INC-53EC / REFC-03: acquire() теперь sync + threading.Lock;
        acquire_async() обёртка для async-контекста).
        """
        limiter = SlidingWindowRateLimiter()
        for _ in range(5):
            assert await limiter.acquire_async("test", max_per_sec=5) is True

    @pytest.mark.asyncio
    async def test_acquire_exceeds_limit(self):
        """acquire_async возвращает False если лимит превышен."""
        limiter = SlidingWindowRateLimiter()
        for _ in range(5):
            await limiter.acquire_async("test", max_per_sec=5)
        # 6-й запрос должен быть отклонён
        assert await limiter.acquire_async("test", max_per_sec=5) is False

    @pytest.mark.asyncio
    async def test_different_keys_independent(self):
        """Разные ключи имеют независимые счётчики."""
        limiter = SlidingWindowRateLimiter()
        for _ in range(10):
            await limiter.acquire_async("key_a", max_per_sec=10)
        # key_a исчерпан, key_b — свежий
        assert await limiter.acquire_async("key_a", max_per_sec=10) is False
        assert await limiter.acquire_async("key_b", max_per_sec=10) is True

    @pytest.mark.asyncio
    async def test_window_slides_after_1_second(self):
        """Окно скользит: через 1с старые записи очищаются."""
        limiter = SlidingWindowRateLimiter()
        for _ in range(5):
            await limiter.acquire_async("test", max_per_sec=5)

        # Ждём когда окно очистится
        await asyncio.sleep(1.1)
        assert await limiter.acquire_async("test", max_per_sec=5) is True

    def test_sync_acquire_works(self):
        """acquire() доступен как sync для использования в sync-контексте (NotifyChangeTool)."""
        limiter = SlidingWindowRateLimiter()
        for _ in range(5):
            assert limiter.acquire("test", max_per_sec=5) is True
        assert limiter.acquire("test", max_per_sec=5) is False

    @pytest.mark.asyncio
    async def test_wait_or_skip_returns_true_within_limit(self):
        """wait_or_skip возвращает True если слот освободился."""
        limiter = SlidingWindowRateLimiter()
        assert await limiter.wait_or_skip("test", max_per_sec=5, max_wait_ms=500) is True

    @pytest.mark.asyncio
    async def test_wait_or_skip_returns_false_when_busy(self):
        """wait_or_skip возвращает False если лимит превышен и ожидание не помогло."""
        limiter = SlidingWindowRateLimiter()
        for _ in range(5):
            await limiter.acquire_async("test", max_per_sec=5)
        # 6-й: лимит превышен, ожидание 100ms не поможет
        result = await limiter.wait_or_skip("test", max_per_sec=5, max_wait_ms=100)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """get_stats возвращает корректную статистику."""
        limiter = SlidingWindowRateLimiter()
        for _ in range(3):
            await limiter.acquire_async("test", max_per_sec=10)

        stats = limiter.get_stats("test")
        assert stats["key"] == "test"
        assert stats["requests_last_sec"] == 3
        assert stats["total_tracked"] == 3


# ══════════════════════════════════════════════════════════
# DebounceBatch
# ══════════════════════════════════════════════════════════

class TestDebounceBatch:
    """DebounceBatch — пакетная обработка с debounce."""

    @pytest.mark.asyncio
    async def test_add_accumulates_files(self):
        """add накапливает файлы в батче."""
        collected = []

        def callback(files):
            collected.extend(files)

        batch = DebounceBatch(callback=callback, config=DebounceConfig(
            debounce_ms=1000,  # не сработает за время теста
            max_wait_ms=10000,
        ))

        assert await batch.add("file1.py") is True  # новый
        assert await batch.add("file2.py") is True  # новый
        assert await batch.add("file1.py") is False  # уже есть

        assert await batch.pending_count() == 2

    @pytest.mark.asyncio
    async def test_flush_now_clears_and_calls_callback(self):
        """flush_now немедленно сбрасывает батч в callback."""
        collected = []

        def callback(files):
            collected.extend(files)

        batch = DebounceBatch(callback=callback)
        await batch.add("file1.py")
        await batch.add("file2.py")

        await batch.flush_now()

        assert await batch.pending_count() == 0
        assert "file1.py" in collected
        assert "file2.py" in collected

    @pytest.mark.asyncio
    async def test_max_batch_size_triggers_immediate_flush(self):
        """При достижении max_batch_size батч сбрасывается немедленно."""
        flush_calls = []

        def callback(files):
            flush_calls.append(set(files))

        batch = DebounceBatch(callback=callback, config=DebounceConfig(
            max_batch_size=3,
            debounce_ms=5000,
        ))

        await batch.add("f1.py")
        await batch.add("f2.py")
        assert len(flush_calls) == 0  # ещё не сброшен

        await batch.add("f3.py")  # == max_batch_size → триггер
        assert len(flush_calls) == 1
        assert "f1.py" in flush_calls[0]
        assert "f3.py" in flush_calls[0]

    @pytest.mark.asyncio
    async def test_callback_error_does_not_crash(self):
        """Ошибка в callback не убивает батч."""
        call_count = 0

        def callback(files):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("callback failed")

        batch = DebounceBatch(callback=callback)
        await batch.add("f1.py")
        await batch.flush_now()

        assert call_count == 1  # вызван, несмотря на ошибку

    @pytest.mark.asyncio
    async def test_multiple_adds_before_flush(self):
        """Множественные add до flush обрабатываются одним батчем."""
        call_count = 0
        all_files = []

        def callback(files):
            nonlocal call_count
            call_count += 1
            all_files.extend(files)

        batch = DebounceBatch(callback=callback, config=DebounceConfig(
            debounce_ms=10000,
        ))

        await batch.add("a.py")
        await batch.add("b.py")
        await batch.add("c.py")
        await batch.flush_now()

        assert call_count == 1
        assert len(all_files) == 3


# ══════════════════════════════════════════════════════════
# CircuitBreaker
# ══════════════════════════════════════════════════════════

class TestCircuitBreaker:
    """CircuitBreaker — защита от каскадных сбоев."""

    @pytest.mark.asyncio
    async def test_closed_state_success(self):
        """CLOSED: успешные вызовы проходят."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

        async def success():
            return "ok"

        result = await cb.call(success)
        assert result == "ok"
        assert cb.state == cb.STATE_CLOSED
        assert cb.success_count == 1

    @pytest.mark.asyncio
    async def test_closed_to_open_after_failures(self):
        """CLOSED → OPEN после failure_threshold ошибок."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=30.0)

        async def fail():
            raise ValueError("fail")

        # Первая ошибка — всё ещё CLOSED
        await cb.call(fail, fallback="fb1")
        assert cb.state == cb.STATE_CLOSED
        assert cb.failure_count == 1

        # Вторая — OPEN
        await cb.call(fail, fallback="fb2")
        assert cb.state == cb.STATE_OPEN
        assert cb.failure_count == 2

    @pytest.mark.asyncio
    async def test_open_returns_fallback(self):
        """OPEN: возвращает fallback, не вызывая оригинал."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30.0)
        call_count = 0

        async def fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        # Первый — провал → OPEN
        await cb.call(fail, fallback="fb")
        assert call_count == 1

        # Второй — OPEN, fallback, оригинал НЕ вызывается
        result = await cb.call(fail, fallback="fb")
        assert result == "fb"
        assert call_count == 1  # не увеличился!

    @pytest.mark.asyncio
    async def test_open_to_half_open_after_timeout(self):
        """OPEN → HALF_OPEN после recovery_timeout при попытке call()."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.3)

        async def fail():
            raise ValueError("fail")

        async def success():
            return "recovered"

        # Доводим до OPEN
        await cb.call(fail, fallback="fb")
        assert cb.state == cb.STATE_OPEN

        # Ждём recovery timeout
        await asyncio.sleep(0.4)

        # call() сам переключает OPEN → HALF_OPEN при проверке таймаута
        # Успешный запрос в HALF_OPEN → CLOSED
        result = await cb.call(success)
        assert result == "recovered"
        assert cb.state == cb.STATE_CLOSED

    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_success(self):
        """HALF_OPEN → CLOSED при успешном тестовом запросе."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.3)

        async def fail():
            raise ValueError("fail")

        async def success():
            return "recovered"

        # Доводим до OPEN
        await cb.call(fail, fallback="fb")
        assert cb.state == cb.STATE_OPEN

        # Ждём recovery
        await asyncio.sleep(0.4)

        # Тестовый запрос успешен
        result = await cb.call(success)
        assert result == "recovered"
        assert cb.state == cb.STATE_CLOSED

    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self):
        """HALF_OPEN → OPEN при неудачном тестовом запросе."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.3)

        async def fail():
            raise ValueError("fail")

        # OPEN
        await cb.call(fail, fallback="fb")
        await asyncio.sleep(0.4)  # recovery

        # HALF_OPEN → снова OPEN
        result = await cb.call(fail, fallback="fb")
        assert result == "fb"
        assert cb.state == cb.STATE_OPEN

    @pytest.mark.asyncio
    async def test_get_state(self):
        """get_state возвращает корректную информацию."""
        cb = CircuitBreaker(name="test_cb", failure_threshold=3)
        state = cb.get_state()
        assert state["name"] == "test_cb"
        assert state["state"] == cb.STATE_CLOSED
        assert state["failure_count"] == 0
        assert state["success_count"] == 0
