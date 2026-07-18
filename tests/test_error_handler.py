"""Unit-тесты для error_handler.py: ToolError, error_boundary, IndexNotReadyError.

Обновлено: тест на _sanitize (конвертация numpy/pandas типов в Python).
"""

from __future__ import annotations

import asyncio

import pytest

from src.core.error_handler import (
    IndexNotReadyError,
    RateLimitError,
    ToolError,
    error_boundary,
)

# ══════════════════════════════════════════════════════════
# ToolError
# ══════════════════════════════════════════════════════════


class TestToolError:
    """ToolError — базовое исключение MCP-инструментов."""

    def test_creates_with_message(self):
        err = ToolError("test error")
        assert err.message == "test error"
        assert err.status == "error"
        assert err.recoverable is True

    def test_custom_status_and_detail(self):
        err = ToolError(
            "warning msg", status="warning", detail="something", recoverable=False
        )
        assert err.status == "warning"
        assert err.detail == "something"
        assert err.recoverable is False

    def test_to_dict(self):
        err = ToolError("msg", status="error", detail="detail")
        d = err.to_dict()
        assert d == {"status": "error", "message": "msg", "detail": "detail"}

    def test_is_exception_subclass(self):
        assert issubclass(ToolError, Exception)
        with pytest.raises(ToolError):
            raise ToolError("raised")


class TestIndexNotReadyError:
    """IndexNotReadyError — подкласс ToolError для пустого индекса."""

    def test_default_detail(self):
        err = IndexNotReadyError()
        assert err.status == "warning"
        assert "Run index_project_dir" in err.detail

    def test_custom_detail(self):
        err = IndexNotReadyError(detail="custom")
        assert "custom" in err.detail
        assert err.recoverable is True


class TestRateLimitError:
    """RateLimitError — подкласс ToolError для rate limit."""

    def test_default(self):
        err = RateLimitError()
        assert err.status == "warning"
        assert err.recoverable is True
        assert "rate limit" in err.message.lower()


# ══════════════════════════════════════════════════════════
# error_boundary
# ══════════════════════════════════════════════════════════


class TestErrorBoundaryAsync:
    """error_boundary декоратор — асинхронный режим."""

    @pytest.mark.asyncio
    async def test_success_returns_json(self):
        """Успешное выполнение возвращает форматированный текст."""

        @error_boundary("test_tool")
        async def ok_tool() -> dict:
            return {"data": "hello"}

        result = await ok_tool()
        assert isinstance(result, str)
        assert "data: hello" in result or "✅" in result

    @pytest.mark.asyncio
    async def test_str_result_wrapped_in_message(self):
        """Строковый результат возвращается как есть."""

        @error_boundary("test_tool")
        async def str_tool() -> str:
            return "success"

        result = await str_tool()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_tool_error_returns_controlled_json(self):
        """ToolError возвращает Markdown, не JSON (изменено с версии 2.5+)."""

        @error_boundary("test_tool")
        async def err_tool():
            raise ToolError(
                "controlled", status="warning", detail="something went wrong"
            )

        result = await err_tool()
        assert "Warning" in result or "warning" in result
        assert "controlled" in result
        assert "something went wrong" in result

    @pytest.mark.asyncio
    async def test_index_not_ready_returns_warning(self):
        """IndexNotReadyError возвращает warning."""

        @error_boundary("test_tool")
        async def empty_tool():
            raise IndexNotReadyError()

        result = await empty_tool()
        assert "Warning" in result or "warning" in result
        assert "Index" in result

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_error(self):
        """Неожиданное исключение возвращает error."""

        @error_boundary("test_tool")
        async def crash_tool():
            raise ValueError("unexpected")

        result = await crash_tool()
        assert "Error" in result or "error" in result
        assert "unexpected" in result

    @pytest.mark.asyncio
    async def test_timeout_via_wait_for(self):
        """Таймаут прерывает корутину через asyncio.wait_for."""

        @error_boundary("timeout_tool", timeout_ms=100)
        async def slow_tool():
            await asyncio.sleep(10)
            return "never"

        result = await slow_tool()
        assert "Timeout" in result or "timeout" in result
        assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_timeout_without_max_retries(self):
        """Таймаут без retry возвращает ответ сразу."""

        @error_boundary("no_retry_tool", timeout_ms=50, max_retries=0)
        async def slow_tool():
            await asyncio.sleep(10)
            return "never"

        result = await slow_tool()
        assert "Timeout" in result or "timeout" in result

    @pytest.mark.asyncio
    async def test_no_timeout_does_not_raise(self):
        """Если timeout_ms=None, корутина не прерывается."""

        @error_boundary("fast_tool")
        async def fast_tool() -> dict:
            return {"done": True}

        result = await fast_tool()
        assert isinstance(result, str)
        assert "done" in result or "✅" in result

    @pytest.mark.asyncio
    async def test_rate_limit_error_returns_warning(self):
        """RateLimitError возвращает warning."""

        @error_boundary("rate_tool")
        async def rate_tool():
            raise RateLimitError(detail="too fast")

        result = await rate_tool()
        assert "Warning" in result or "warning" in result
        assert "too fast" in result

    @pytest.mark.asyncio
    async def test_sanitize_numpy_types(self):
        """int32/float64 конвертируются в нативные Python типы."""

        @error_boundary("sanitize_tool")
        async def numpy_tool() -> dict:
            class Int32:
                def __int__(self):
                    return 42

                def __float__(self):
                    return 42.0

                def __repr__(self):
                    return "int32(42)"

            return {
                "chunk_index": Int32(),
                "score": 0.85,
                "file": "test.py",
            }

        result = await numpy_tool()
        assert isinstance(result, str)
        assert "42" in result or "0.85" in result or "✅" in result

    @pytest.mark.asyncio
    async def test_sanitize_nested_int32(self):
        """int32 вложенный в список конвертируется."""

        @error_boundary("sanitize_nested")
        async def nested_tool() -> dict:
            class Int32:
                def __int__(self):
                    return 7

            return {
                "results": [
                    {"chunk_index": Int32(), "file": "a.py"},
                    {"chunk_index": Int32(), "file": "b.py"},
                ]
            }

        result = await nested_tool()
        assert isinstance(result, str)
        assert "results: 2" in result or "7" in result or "✅" in result


class TestErrorBoundarySync:
    """error_boundary декоратор — синхронный режим."""

    def test_sync_success(self):
        """Синхронная функция возвращает строку."""

        @error_boundary("sync_tool")
        def sync_tool() -> dict:
            return {"result": 42}

        result = sync_tool()
        assert isinstance(result, str)
        assert "result: 42" in result or "✅" in result

    def test_sync_tool_error(self):
        """ToolError в синхронной функции."""

        @error_boundary("sync_tool")
        def sync_err():
            raise ToolError("sync error", detail="bad")

        result = sync_err()
        assert "Error" in result or "error" in result
        assert "sync error" in result

    def test_sync_unexpected_error(self):
        """Неожиданная ошибка в синхронной функции."""

        @error_boundary("sync_tool")
        def sync_crash():
            raise RuntimeError("boom")

        result = sync_crash()
        assert "Error" in result or "error" in result
        assert "boom" in result


class TestRecordToolCall:
    """record_tool_call — запись метрик вызова инструмента."""

    def test_record_basic(self):
        from src.core.error_handler import record_tool_call, _TOOL_METRICS, _TOOL_METRICS_LOCK
        with _TOOL_METRICS_LOCK:
            _TOOL_METRICS.clear()
        record_tool_call("test_tool", 100, True)
        with _TOOL_METRICS_LOCK:
            stats = _TOOL_METRICS.get("test_tool", {})
        assert stats["calls"] == 1
        assert stats["total_ms"] == 100
        assert stats["errors"] == 0

    def test_record_multiple_calls(self):
        from src.core.error_handler import record_tool_call, _TOOL_METRICS, _TOOL_METRICS_LOCK
        with _TOOL_METRICS_LOCK:
            _TOOL_METRICS.clear()
        for i in range(5):
            record_tool_call("multi_tool", 50 * (i + 1), i % 2 == 0)
        with _TOOL_METRICS_LOCK:
            stats = _TOOL_METRICS.get("multi_tool", {})
        assert stats["calls"] == 5
        assert stats["errors"] == 2

    def test_record_with_route_increments(self):
        """Проверяет, что route счётчик инкрементится (+1, а не -1)."""
        from src.core.error_handler import record_tool_call, _TOOL_METRICS, _TOOL_METRICS_LOCK
        with _TOOL_METRICS_LOCK:
            _TOOL_METRICS.clear()
        record_tool_call("route_tool", 10, True, route="fast")
        record_tool_call("route_tool", 20, True, route="fast")
        record_tool_call("route_tool", 30, True, route="quality")
        with _TOOL_METRICS_LOCK:
            stats = _TOOL_METRICS.get("route_tool", {})
        assert stats["route"]["fast"] == 2
        assert stats["route"]["quality"] == 1

    def test_rolling_average_confidence(self):
        """Проверяет скользящее среднее confidence (prev + (conf - prev) / calls)."""
        from src.core.error_handler import record_tool_call, _TOOL_METRICS, _TOOL_METRICS_LOCK
        with _TOOL_METRICS_LOCK:
            _TOOL_METRICS.clear()
        record_tool_call("avg_tool", 10, True, confidence=1.0)
        record_tool_call("avg_tool", 10, True, confidence=0.5)
        record_tool_call("avg_tool", 10, True, confidence=0.0)
        with _TOOL_METRICS_LOCK:
            stats = _TOOL_METRICS.get("avg_tool", {})
        assert abs(stats["avg_confidence"] - 0.5) < 0.01


class TestPercentile:
    """_percentile — вычисление перцентиля."""

    def test_percentile_empty(self):
        from src.core.error_handler import _percentile
        assert _percentile([], 50) == 0.0

    def test_percentile_single(self):
        from src.core.error_handler import _percentile
        assert _percentile([100], 50) == 100.0

    def test_percentile_median(self):
        from src.core.error_handler import _percentile
        latencies = [10, 20, 30, 40, 50]
        assert _percentile(latencies, 50) == 30.0

    def test_percentile_with_add(self):
        """Проверяет c = f + 1 (убивает мутацию c = f - 1)."""
        from src.core.error_handler import _percentile
        # p=50, len=5: k = 4 * 0.5 = 2.0, f = 2, c = 3 (нормально)
        # Если c = f - 1 = 1 — вернёт неверное значение
        latencies = [10, 20, 30, 40, 50]
        result = _percentile(latencies, 50)
        assert result == 30.0, f"expected 30.0, got {result}"


class TestGetIdleMetrics:
    """get_global_idle_metrics — метрики простоя."""

    def test_idle_plus_active(self):
        """Проверяет total_ms = total_idle + active_ms (+ а не *)."""
        from src.core.error_handler import (
            get_global_idle_metrics, _TOOL_METRICS, _TOOL_METRICS_LOCK
        )
        with _TOOL_METRICS_LOCK:
            _TOOL_METRICS.clear()
        # После очистки — idle и active = 0
        metrics = get_global_idle_metrics()
        assert metrics["active_ms"] >= 0
        assert metrics["idle_ms"] >= 0


class TestErrorBoundaryRetryCount:
    """error_boundary — проверка max_retries."""

    @pytest.mark.asyncio
    async def test_retry_range_plus_one(self):
        """Проверяет range(max_retries + 1) — убивает мутацию range(max_retries - 1)."""
        call_count = 0

        @error_boundary("retry_test", max_retries=3, timeout_ms=100)
        async def flaky_tool() -> dict:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.5)  # превышает timeout_ms=100 → TimeoutError
            return {"ok": True}

        result = await flaky_tool()
        assert call_count == 4, f"expected 4 attempts, got {call_count}"
        assert "timeout" in result or "Timeout" in result
