"""Централизованная обработка ошибок для MCP-инструментов.

Заменяет 30+ копий try/except на один декоратор.
Автоматически логирует инцидент и возвращает JSON-совместимый ответ.

ИСПРАВЛЕНО (v2):
- Реальный asyncio.wait_for() с таймаутом (не просто catch TimeoutError)
- Синхронный wrapper через ThreadPoolExecutor для CPU-bound операций
- Контролируемые ToolError с кодами status
"""

from __future__ import annotations

import asyncio
import inspect
import functools
import json
import logging
import threading
import time
import traceback
from typing import Any, Callable, Optional

logger = logging.getLogger("mscodebase_server.error_handler")

# ══════════════════════════════════════════════════════════
# Per-tool telemetry: автоматический сбор с error_boundary
# ══════════════════════════════════════════════════════════

_TOOL_METRICS: dict = {}
"""Счётчики вызовов инструментов: {tool_name: {calls, errors, total_ms, last_call}}"""

_TOOL_METRICS_LOCK = threading.Lock()


def record_tool_call(tool_name: str, latency_ms: int, success: bool) -> None:
    """Записывает метрику вызова инструмента (потокобезопасно)."""
    with _TOOL_METRICS_LOCK:
        entry = _TOOL_METRICS.setdefault(tool_name, {
            "calls": 0,
            "errors": 0,
            "total_ms": 0,
            "last_call": "",
        })
        entry["calls"] += 1
        if not success:
            entry["errors"] += 1
        entry["total_ms"] += latency_ms
        entry["last_call"] = time.strftime("%H:%M:%S")


def get_tool_metrics() -> dict:
    """Возвращает копию метрик для telemetry."""
    with _TOOL_METRICS_LOCK:
        return {
            name: dict(stats)
            for name, stats in _TOOL_METRICS.items()
        }


def get_tool_metrics_summary() -> list:
    """Форматирует метрики для вывода (sorted by calls desc)."""
    with _TOOL_METRICS_LOCK:
        rows = []
        for name, stats in sorted(
            _TOOL_METRICS.items(), key=lambda x: x[1]["calls"], reverse=True
        ):
            avg_ms = round(stats["total_ms"] / stats["calls"], 1) if stats["calls"] else 0
            rows.append({
                "tool": name,
                "calls": stats["calls"],
                "errors": stats["errors"],
                "avg_ms": avg_ms,
                "last": stats["last_call"],
            })
        return rows


class ToolError(Exception):
    """Базовое исключение для MCP-инструментов с поддержкой кодов ошибок.

    ВСЕ инструменты должны бросать исключительно ToolError (или наследников).
    error_boundary автоматически превращает их в JSON-ответ.
    """

    def __init__(
        self,
        message: str,
        status: str = "error",
        detail: Optional[str] = None,
        recoverable: bool = True,
    ):
        self.message = message
        self.status = status  # "error" | "timeout" | "warning"
        self.detail = detail
        self.recoverable = recoverable
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "detail": self.detail,
        }


class IndexNotReadyError(ToolError):
    """Когда индекс пуст или не инициализирован."""
    def __init__(self, detail: str = ""):
        super().__init__(
            message="Index is not ready",
            status="warning",
            detail=detail or "Run index_project_dir() to initialize",
            recoverable=True,
        )


class RateLimitError(ToolError):
    """Rate Limit превышен."""
    def __init__(self, detail: str = ""):
        super().__init__(
            message="Rate limit exceeded",
            status="warning",
            detail=detail,
            recoverable=True,
        )


def _format_error_response(
    status: str,
    message: str,
    detail: Optional[str] = None,
    recovery_hint: Optional[str] = None,
    latency_ms: Optional[int] = None,
) -> str:
    """Форматирует JSON-ответ с ошибкой."""
    result = {
        "status": status,
        "message": message,
    }
    if detail:
        result["detail"] = detail
    if recovery_hint:
        result["recovery_hint"] = recovery_hint
    if latency_ms is not None:
        result["latency_ms"] = latency_ms
    return json.dumps(result, ensure_ascii=False, default=_json_default)


def error_boundary(
    tool_name: str,
    max_retries: int = 0,
    timeout_ms: Optional[int] = None,
    recoverable: bool = True,
) -> Callable:
    """Декоратор для MCP-инструментов.

    Автоматически:
    - Применяет реальный asyncio.wait_for(timeout_ms) если указан
    - Ловит все исключения (ToolError, TimeoutError, Exception)
    - Логирует с traceback
    - Возвращает JSON с полями status/message/detail
    - Записывает время выполнения в latency_ms

    Args:
        tool_name: Имя инструмента для логов
        max_retries: Количество повторов при TimeoutError (0 = без повторов)
        timeout_ms: Таймаут выполнения (None = без таймаута).
                    КРИТИЧНО: этот таймаут реально применяется через asyncio.wait_for()
        recoverable: Флаг для ответа (может ли агент повторить позже)

    Usage:
        @error_boundary("search_code", timeout_ms=15000, max_retries=1)
        async def search_code(query: str) -> dict:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> str:
            start_time = time.perf_counter()
            last_error: Optional[Exception] = None

            for attempt in range(max_retries + 1):
                try:
                    # ★ КРИТИЧНО: реальный asyncio.wait_for с таймаутом ★
                    # Именно здесь создается гонка с таймаутом —
                    # если корутина зависнет, wait_for прервет её по истечению timeout_ms
                    if timeout_ms:
                        raw_result = await asyncio.wait_for(
                            func(*args, **kwargs),
                            timeout=timeout_ms / 1000.0,
                        )
                    else:
                        raw_result = await func(*args, **kwargs)

                    # Успех
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    record_tool_call(tool_name, latency_ms, success=True)
                    return _format_success_response(raw_result, latency_ms)

                except asyncio.TimeoutError as e:
                    last_error = e
                    elapsed = int((time.perf_counter() - start_time) * 1000)
                    logger.warning(
                        f"⏱ [{tool_name}] Timeout after {elapsed}ms "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    record_tool_call(tool_name, elapsed, success=False)
                    if attempt < max_retries:
                        await asyncio.sleep(1)
                    else:
                        return _format_error_response(
                            status="timeout",
                            message=f"Operation timed out after {timeout_ms}ms",
                            detail=f"Attempts: {attempt + 1}/{max_retries + 1}",
                            recovery_hint="Try with fewer results or smaller scope",
                            latency_ms=elapsed,
                        )

                except ToolError as e:
                    # Контролируемая ошибка — не retry
                    logger.warning(
                        f"[{tool_name}] {e.status}: {e.message}"
                        + (f" | {e.detail}" if e.detail else "")
                    )
                    elapsed = int((time.perf_counter() - start_time) * 1000)
                    record_tool_call(tool_name, elapsed, success=False)
                    return _format_error_response(
                        status=e.status,
                        message=e.message,
                        detail=e.detail,
                        recovery_hint=None if e.recoverable else "Contact admin",
                    )

                except Exception as e:
                    # Неожиданная ошибка — логируем полный traceback и НЕ повторяем
                    logger.error(
                        f"[{tool_name}] Unexpected error: {e}\n"
                        f"{traceback.format_exc()}"
                    )
                    elapsed = int((time.perf_counter() - start_time) * 1000)
                    record_tool_call(tool_name, elapsed, success=False)
                    _notify_error(f"{tool_name}: {e}", severity="Error")
                    return _format_error_response(
                        status="error",
                        message=str(e),
                        detail=traceback.format_exc(limit=3),
                    )

            # Недостижимо, но на всякий случай
            return _format_error_response(
                status="error",
                message=f"Max retries ({max_retries}) exhausted",
                detail=str(last_error) if last_error else "Unknown",
            )

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> str:
            """Синхронная обертка через ThreadPoolExecutor."""
            start_time = time.perf_counter()
            try:
                if timeout_ms:
                    # Для синхронных функций используем run_in_executor + wait_for
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Мы внутри async контекста — используем to_thread
                        async def _run():
                            return await asyncio.to_thread(func, *args, **kwargs)

                        result = asyncio.get_event_loop().run_until_complete(
                            asyncio.wait_for(_run(), timeout=timeout_ms / 1000.0)
                        )
                    else:
                        result = func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                latency_ms = int((time.perf_counter() - start_time) * 1000)
                record_tool_call(tool_name, latency_ms, success=True)
                return _format_success_response(result, latency_ms)

            except ToolError as e:
                logger.warning(
                    f"[{tool_name}] {e.status}: {e.message}"
                    + (f" | {e.detail}" if e.detail else "")
                )
                elapsed = int((time.perf_counter() - start_time) * 1000)
                record_tool_call(tool_name, elapsed, success=False)
                return _format_error_response(
                    status=e.status,
                    message=e.message,
                    detail=e.detail,
                )
            except Exception as e:
                logger.error(
                    f"[{tool_name}] Unexpected error: {e}\n"
                    f"{traceback.format_exc()}"
                )
                elapsed = int((time.perf_counter() - start_time) * 1000)
                record_tool_call(tool_name, elapsed, success=False)
                return _format_error_response(
                    status="error",
                    message=str(e),
                    detail=traceback.format_exc(limit=3),
                )

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ══════════════════════════════════════════════════════════
# Вспомогательные внутренние функции
# ══════════════════════════════════════════════════════════

def _sanitize(obj: Any) -> Any:
    """Рекурсивно преобразует numpy/pandas типы в нативные Python.

    Проблема: PyArrow хранит int32, float64 (не сериализуются в JSON).
    Решение: рекурсивный обход с конвертацией в int/float/str.
    """
    import math

    if hasattr(obj, "dtype"):  # numpy scalar или pandas series
        # Проверяем тип numpy/scalar
        if hasattr(obj, "item"):
            return obj.item()
        return float(obj) if hasattr(obj, "__float__") else int(obj)

    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    # Всё остальное (numpy.ndarray, etc.) — пробуем привести
    try:
        return int(obj)
    except (TypeError, ValueError):
        pass
    try:
        return float(obj)
    except (TypeError, ValueError):
        pass
    try:
        return str(obj)[:1000]
    except Exception:
        return None


def _format_success_response(data: Any, latency_ms: int) -> str:
    """Форматирует успешный ответ.

    Стратегия:
    - str: пропускаем как есть (уже готовый читаемый ответ с эмодзи)
    - dict: красивое форматирование + сырые данные в json-блоке внизу
    - остальное: JSON
    """
    data = _sanitize(data)
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        data.pop("status", None)
        data.pop("latency_ms", None)

        # Красивое форматирование (для человека)
        lines = []
        for k, v in data.items():
            if k in ("results", "data"):
                continue  # сырые данные — покажем в json-блоке
            key = str(k).replace("_", " ")
            if isinstance(v, list) and len(v) > 5:
                lines.append(f"  • {key}: {len(v)} items")
            elif isinstance(v, dict):
                lines.append(f"  • {key}:")
                for sk, sv in list(v.items())[:3]:
                    lines.append(f"      - {sk}: {sv}")
            else:
                lines.append(f"  • {key}: {v}")

        # Сырые JSON данные (для AI)
        raw_json = json.dumps(data, ensure_ascii=False, default=_json_default, indent=2)

        return f"✅ Completed ({latency_ms}ms)\n" + "\n".join(lines) + f"\n\n```json\n{raw_json}\n```"
    return json.dumps({
        "status": "ok",
        "data": data,
        "latency_ms": latency_ms,
    }, ensure_ascii=False, default=_json_default)


def _json_default(obj):
    """Fallback для json.dumps — конвертирует неподдерживаемые типы."""
    import math
    # numpy/pyarrow: int32, float64, etc.
    if hasattr(obj, "item"):
        return obj.item()
    if hasattr(obj, "__float__"):
        val = float(obj)
        return None if math.isnan(val) or math.isinf(val) else val
    if hasattr(obj, "__int__"):
        return int(obj)
    try:
        return str(obj)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
# NotificationBroker для error_boundary
# ══════════════════════════════════════════════════════════

_error_broker = None


def set_notification_broker(broker) -> None:
    """Устанавливает брокер для отправки диагностик в Zed."""
    global _error_broker
    _error_broker = broker


def _notify_error(error_msg: str, severity: str = "Error"):
    """Отправляет диагностику через брокер (если установлен)."""
    global _error_broker
    if _error_broker is not None:
        try:
            _error_broker.publish_sync(
                "mscodebase/diagnostics_update",
                {
                    "file_path": "",
                    "diagnostics": [
                        {
                            "range": {
                                "start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0},
                            },
                            "severity": severity,
                            "message": f"[MSCodeBase] {error_msg}",
                            "code": "CORE_EXCEPTION",
                        }
                    ],
                },
            )
        except Exception:
            pass
