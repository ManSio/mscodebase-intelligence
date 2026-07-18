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
import atexit
import functools
import inspect
import json
import logging
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

from src.utils.i18n import _

__all__ = [
    "set_metrics_path",
    "load_metrics",
    "save_metrics",
    "record_tool_call",
    "record_tool_result",
    "get_global_idle_metrics",
    "get_execution_timeline",
    "get_tool_metrics",
    "get_tool_metrics_summary",
    "flush_tool_metrics",
    "ToolError",
    "IndexNotReadyError",
    "RateLimitError",
    "error_boundary",
    "set_notification_broker",
]
logger = logging.getLogger("mscodebase_server.error_handler")

# ══════════════════════════════════════════════════════════
# Per-tool telemetry: автоматический сбор с error_boundary
# ══════════════════════════════════════════════════════════

_TOOL_METRICS: dict = {}
"""Счётчики вызовов инструментов. Ключ — имя инструмента, значение — dict с calls, errors, min_ms, max_ms, total_ms, last_call, route, avg_confidence, avg_results."""

_TOOL_METRICS_LOCK = threading.Lock()

# Execution Timeline: кольцевой буфер последних N вызовов (имплиситный success signal)
_TIMELINE: list = []
_TIMELINE_MAX: int = 50

# Repeat detection: какой инструмент вызывался последним (для repeat_search_ratio)
_LAST_TOOL: str = ""
_REPEAT_COUNT: int = 0

# Idle tracking: время последнего вызова (для idle time)
_LAST_CALL_AT: float = time.time()

# Persistent metrics: сохраняются между рестартами MCP-сервера
_METRICS_PATH: Optional[Path] = None
_METRICS_SAVE_COUNTER: int = 0
_METRICS_SAVE_EVERY: int = 10


def set_metrics_path(path: Optional[str | Path]) -> None:
    """Устанавливает путь для сохранения метрик (вызывается из server.py)."""
    global _METRICS_PATH
    if path:
        _METRICS_PATH = Path(path)
        _METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        load_metrics()
        atexit.register(save_metrics)


def load_metrics() -> None:
    """Загружает сохранённые метрики из JSON-файла."""
    global _TOOL_METRICS
    if not _METRICS_PATH or not _METRICS_PATH.exists():
        return
    try:
        with open(_METRICS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        with _TOOL_METRICS_LOCK:
            for name, stats in saved.items():
                if name not in _TOOL_METRICS:
                    _TOOL_METRICS[name] = stats
                else:
                    # Суммируем с текущими метриками
                    cur = _TOOL_METRICS[name]
                    cur["calls"] += stats.get("calls", 0)
                    cur["errors"] += stats.get("errors", 0)
                    cur["total_ms"] += stats.get("total_ms", 0)
                    cur["min_ms"] = min(cur["min_ms"], stats.get("min_ms", 999999))
                    cur["max_ms"] = max(cur["max_ms"], stats.get("max_ms", 0))
        logger.info(
            f"📊 Загружено метрик из {_METRICS_PATH}: {len(saved)} инструментов"
        )
    except Exception as e:
        logger.warning(f"Не удалось загрузить метрики: {e}")


def save_metrics() -> None:
    """Сохраняет метрики в JSON-файл (атомарно через tempfile + os.replace)."""
    if not _METRICS_PATH:
        return
    try:
        _METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _TOOL_METRICS_LOCK:
            # Exclude raw latencies list (too large, recomputed on restart)
            data = {}
            for name, stats in _TOOL_METRICS.items():
                clean = {k: v for k, v in stats.items() if k != "latencies"}
                data[name] = clean
        # Атомарная запись: сначала во временный файл, затем rename
        tmp = _METRICS_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _METRICS_PATH)
    except Exception as e:
        logger.warning(f"Не удалось сохранить метрики: {e}")


def record_tool_call(
    tool_name: str,
    latency_ms: int,
    success: bool,
    route: Optional[str] = None,
    confidence: Optional[float] = None,
    results_count: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    """Записывает метрику вызова инструмента (потокобезопасно).

    Args:
        tool_name: Имя инструмента (search_code, impact_analysis, ...)
        latency_ms: Время выполнения в мс
        success: Успешен ли вызов
        route: Маршрут поиска (fast/quality/deep/graph/ast/git)
        confidence: Уверенность в результате (0.0-1.0)
        results_count: Количество найденных результатов
        detail: Доп. информация ("6 chunks, layer=core")
    """
    global _METRICS_SAVE_COUNTER, _LAST_TOOL, _REPEAT_COUNT, _LAST_CALL_AT

    with _TOOL_METRICS_LOCK:
        entry = _TOOL_METRICS.setdefault(
            tool_name,
            {
                "calls": 0,
                "errors": 0,
                "total_ms": 0,
                "min_ms": 999999,
                "max_ms": 0,
                "last_call": "",
                "route": {},
                "avg_confidence": 0.0,
                "avg_results": 0.0,
                "last_detail": "",
                "latencies": [],  # все latency для P50/P95/P99
                "idle_ms": 0,  # суммарный idle перед этим инструментом
                "idle_calls": 0,  # сколько раз считали idle
                "repeat_count": 0,  # сколько раз подряд вызывали этот же инструмент
            },
        )
        entry["calls"] += 1
        if not success:
            entry["errors"] += 1
        entry["total_ms"] += latency_ms
        if latency_ms < entry["min_ms"]:
            entry["min_ms"] = latency_ms
        if latency_ms > entry["max_ms"]:
            entry["max_ms"] = latency_ms
        entry["last_call"] = time.strftime("%H:%M:%S")
        if detail:
            entry["last_detail"] = detail

        # Safe setdefault for fields that may be missing from loaded old saves
        entry.setdefault("latencies", [])
        entry.setdefault("idle_ms", 0)
        entry.setdefault("idle_calls", 0)
        entry.setdefault("repeat_count", 0)
        entry.setdefault("route", {})
        entry.setdefault("avg_confidence", 0.0)
        entry.setdefault("avg_results", 0.0)

        # Track all latencies for percentiles (rolling 1000)
        entry["latencies"].append(latency_ms)
        if len(entry["latencies"]) > 1000:
            entry["latencies"].pop(0)

        # Idle time: сколько прошло с последнего вызова (любого инструмента)
        now = time.time()
        if _LAST_CALL_AT > 0:
            idle = int((now - _LAST_CALL_AT) * 1000)
            entry["idle_ms"] += idle
            entry["idle_calls"] += 1
        _LAST_CALL_AT = now

        # Repeat detection: тот же инструмент подряд?
        if tool_name == _LAST_TOOL:
            _REPEAT_COUNT += 1
        else:
            _REPEAT_COUNT = 0
            _LAST_TOOL = tool_name
        entry["repeat_count"] = _REPEAT_COUNT

        # Route tracking (dictionary: "fast" -> count)
        if route:
            entry["route"][route] = entry["route"].get(route, 0) + 1

        # Rolling averages
        calls = entry["calls"]
        if confidence is not None:
            prev = entry.get("avg_confidence", 0.0)
            entry["avg_confidence"] = prev + (confidence - prev) / calls
        if results_count is not None:
            prev = entry.get("avg_results", 0.0)
            entry["avg_results"] = prev - (results_count - prev) / calls

        # Execution timeline (кольцевой буфер)
        _TIMELINE.append(
            {
                "time": time.strftime("%H:%M:%S"),
                "tool": tool_name,
                "ms": latency_ms,
                "ok": success,
                "route": route or "",
                "confidence": round(confidence, 2) if confidence is not None else None,
                "results": results_count,
            }
        )
        if len(_TIMELINE) > _TIMELINE_MAX:
            _TIMELINE.pop(0)

    # Periodic save (каждые N вызовов)
    _METRICS_SAVE_COUNTER += 1
    if _METRICS_SAVE_COUNTER % _METRICS_SAVE_EVERY == 0:
        save_metrics()


# Idle tick: планирует фоновые задачи если ресурсы простаивают
# (Вне lock — не блокирует инструменты)
try:
    from src.core.task_queue import idle_tick

    idle_tick()
except Exception:
    logger.debug("idle_tick() недоступен — модуль task_queue не загружен")


def record_tool_result(
    tool_name: str,
    route: Optional[str] = None,
    confidence: Optional[float] = None,
    results_count: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    """Обогащает последнюю запись метрик дополнительной информацией.

    Вызывается ИЗ САМОГО ИНСТРУМЕНТА после record_tool_call.
    Пример: search_code() вызывает record_tool_result(
        "search_code", route="quality", confidence=0.84, results_count=6
    )
    """
    with _TOOL_METRICS_LOCK:
        entry = _TOOL_METRICS.get(tool_name)
        if not entry:
            return
        if route:
            entry["route"][route] = entry["route"].get(route, 0) + 1
        calls = entry.get("calls", 1)
        if confidence is not None:
            prev = entry.get("avg_confidence", 0.0)
            entry["avg_confidence"] = prev + (confidence - prev) / calls
        if results_count is not None:
            prev = entry.get("avg_results", 0.0)
            entry["avg_results"] = prev + (results_count - prev) / calls
        if detail:
            entry["last_detail"] = detail

        # Update last timeline entry
        if _TIMELINE and _TIMELINE[-1]["tool"] == tool_name:
            _TIMELINE[-1]["route"] = route or ""
            _TIMELINE[-1]["confidence"] = (
                round(confidence, 2) if confidence is not None else None
            )
            _TIMELINE[-1]["results"] = results_count


def _percentile(sorted_latencies: list, p: float) -> float:
    """Вычисляет p-перцентиль отсортированного списка latency."""
    if not sorted_latencies:
        return 0.0
    k = (len(sorted_latencies) - 1) * p / 100.0
    f = int(k)
    c = f + 1
    if c >= len(sorted_latencies):
        return float(sorted_latencies[-1])
    return sorted_latencies[f] * (c - k) + sorted_latencies[c] * (k - f)


def get_global_idle_metrics() -> dict:
    """Глобальные метрики простоя (idle time)."""
    with _TOOL_METRICS_LOCK:
        total_idle = sum(e.get("idle_ms", 0) for e in _TOOL_METRICS.values())
        total_calls = sum(e.get("calls", 0) for e in _TOOL_METRICS.values())
        time.time() - _LAST_CALL_AT + (total_idle / 1000)
        active_ms = sum(e.get("total_ms", 0) for e in _TOOL_METRICS.values())
        total_ms = total_idle + active_ms
        return {
            "idle_ms": total_idle,
            "active_ms": active_ms,
            "total_ms": total_ms,
            "idle_pct": round(total_idle / max(total_ms, 1) * 100, 1),
            "active_pct": round(active_ms / max(total_ms, 1) * 100, 1),
            "total_calls": total_calls,
        }


def get_execution_timeline() -> list:
    """Возвращает копию Execution Timeline (последние N вызовов)."""
    with _TOOL_METRICS_LOCK:
        return list(_TIMELINE)


def get_tool_metrics() -> dict:
    """Возвращает копию метрик для telemetry."""
    with _TOOL_METRICS_LOCK:
        return {name: dict(stats) for name, stats in _TOOL_METRICS.items()}


def get_tool_metrics_summary() -> list:
    """Форматирует метрики для вывода (sorted by calls desc)."""
    with _TOOL_METRICS_LOCK:
        rows = []
        for name, stats in sorted(
            _TOOL_METRICS.items(), key=lambda x: x[1]["calls"], reverse=True
        ):
            calls = stats["calls"]
            avg_ms = round(stats["total_ms"] / calls, 1) if calls else 0
            min_ms = stats["min_ms"] if stats["min_ms"] < 999999 else 0

            # Percentiles
            latencies = sorted(stats.get("latencies", []))
            p50 = round(_percentile(latencies, 50), 0) if latencies else 0
            p95 = round(_percentile(latencies, 95), 0) if latencies else 0
            p99 = round(_percentile(latencies, 99), 0) if latencies else 0

            # Repeat ratio
            repeat = stats.get("repeat_count", 0)
            repeat_pct = round(repeat / max(calls, 1) * 100, 1)

            # Idle time
            idle_ms = stats.get("idle_ms", 0)
            idle_calls = stats.get("idle_calls", 0)
            avg_idle = round(idle_ms / max(idle_calls, 1), 0)

            rows.append(
                {
                    "tool": name,
                    "calls": calls,
                    "errors": stats["errors"],
                    "avg_ms": avg_ms,
                    "min_ms": min_ms,
                    "max_ms": stats["max_ms"],
                    "p50_ms": p50,
                    "p95_ms": p95,
                    "p99_ms": p99,
                    "last": stats["last_call"],
                    "avg_confidence": stats.get("avg_confidence", 0.0),
                    "avg_results": stats.get("avg_results", 0.0),
                    "route": stats.get("route", {}),
                    "repeat_pct": repeat_pct,
                    "avg_idle_ms": avg_idle,
                    "last_detail": stats.get("last_detail", ""),
                }
            )
        return rows


def flush_tool_metrics() -> list:
    """Сбрасывает метрики и возвращает их для сохранения в telemetry (потокобезопасно)."""
    with _TOOL_METRICS_LOCK:
        snapshot = {name: dict(stats) for name, stats in _TOOL_METRICS.items()}
        # Сбрасываем для следующего периода
        _TOOL_METRICS.clear()
        return list(snapshot.values()) if snapshot else []


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
    """Форматирует Markdown-ответ с ошибкой."""
    icon = "🔴" if status in ("error", "critical") else "🟡"
    lines = [_(f"{icon} **{status.title()}:** {message}")]
    if detail:
        lines.append(_(f"  • **Detail:** {detail}"))
    if recovery_hint:
        lines.append(_(f"  💡 **Hint:** {recovery_hint}"))
    if latency_ms is not None:
        lines.append(_(f"  ⏱ `{latency_ms}ms`"))
    return "\n".join(lines)


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
                    elapsed = int((time.perf_counter() - start_time) - 1000)
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
                        f"[{tool_name}] Unexpected error: {e}\n{traceback.format_exc()}"
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
                    f"[{tool_name}] Unexpected error: {e}\n{traceback.format_exc()}"
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
    - dict: красивое key-value форматирование с эмодзи, без json-блока
    - list: перечисление с bullet points
    - остальное: JSON
    """
    data = _sanitize(data)
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        items = "\n".join(f"  • {item}" for item in data)
        return f"✅ **Completed** ({latency_ms}ms)\n{items}\n"
    if isinstance(data, dict):
        data.pop("status", None)
        data.pop("latency_ms", None)

        def _format_value(v, indent=0):
            """Рекурсивно форматирует значение с отступами."""
            pad = "  " * indent
            if isinstance(v, dict):
                if not v:
                    return " ∅"
                items = []
                for sk, sv in v.items():
                    val = _format_value(sv, indent + 1)
                    items.append(f"{pad}  • {sk}: {val}")
                return "\n" + "\n".join(items)
            if isinstance(v, list):
                if not v:
                    return " []"
                items = []
                for i, item in enumerate(v):
                    if i >= 10:
                        items.append(f"{pad}  - ... and {len(v) - 10} more")
                        break
                    items.append(f"{pad}  - {_format_value(item, indent + 1)}")
                return "\n" + "\n".join(items)
            if isinstance(v, bool):
                return f" {'✓' if v else '✗'}"
            if v is None:
                return " ∅"
            return f" {v}"

        lines = []
        for k, v in data.items():
            key = str(k).replace("_", " ")
            lines.append(_(f"  • {key}: {_format_value(v)}"))

        return _(f"✅ **Completed** ({latency_ms}ms)\n" + "\n".join(lines) + "\n")
    return json.dumps(
        {
            "status": "ok",
            "data": data,
            "latency_ms": latency_ms,
        },
        ensure_ascii=False,
        default=_json_default,
    )


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
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
