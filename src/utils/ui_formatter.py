"""
MSCodeBase Intelligence — Продуктовый UI-форматтер для вывода MCP-инструментов.

Все инструменты должны проходить через этот модуль для единого стиля вывода:
  - Markdown-таблицы вместо сырого JSON
  - Цветовая кодировка (✅ 🟡 🔴 ℹ️)
  - Технические данные под спойлером
  - Единый заголовок с именем инструмента и временем выполнения
"""

import json
import time
from typing import Any, Dict, List, Optional


def _execution_time(start: float) -> str:
    """Форматирует время выполнения в мс."""
    return f"{(time.monotonic() - start) * 1000:.0f}ms"


def _status_icon(status: str) -> str:
    """Иконка статуса."""
    return {"ok": "✅", "warn": "🟡", "error": "🔴", "info": "ℹ️"}.get(status, "✅")


def _val(val: Any, default: str = "*not set*") -> str:
    """Заменяет None/unknown на читаемый fallback."""
    if val is None or val == "unknown" or val == "":
        return default
    return str(val)


def header(
    tool_name: str,
    status: str = "ok",
    start_time: Optional[float] = None,
    extra: Optional[str] = None,
) -> str:
    """Заголовок инструмента.

    Args:
        tool_name: Имя инструмента (напр. get_repo_rank)
        status: ok | warn | error | info
        start_time: time.monotonic() для расчёта длительности
        extra: Доп. текст после статуса

    Returns:
        Markdown-строка заголовка
    """
    icon = _status_icon(status)
    parts = [f"### {icon} `{tool_name}`"]
    if start_time is not None:
        parts.append(f"— **{_execution_time(start_time)}**")
    if extra:
        parts.append(f"— {extra}")
    return " ".join(parts) + "\n\n"


def table(
    columns: List[str],
    rows: List[List[Any]],
    caption: Optional[str] = None,
) -> str:
    """Форматирует Markdown-таблицу.

    Args:
        columns: Заголовки колонок
        rows: Строки данных
        caption: Подпись над таблицей

    Returns:
        Markdown-таблица
    """
    result = ""
    if caption:
        result += f"*{caption}*\n\n"

    # Разделители
    result += "| " + " | ".join(columns) + " |\n"
    result += "| " + " | ".join(["---"] * len(columns)) + " |\n"

    # Строки
    for row in rows:
        result += "| " + " | ".join(str(cell) for cell in row) + " |\n"

    result += "\n"
    return result


def key_value(items: List[tuple], title: Optional[str] = None) -> str:
    """Список key: value пар.

    Args:
        items: Список (key, value)
        title: Заголовок секции

    Returns:
        Markdown-список
    """
    result = ""
    if title:
        result += f"**{title}**\n\n"

    for key, val in items:
        result += f"- **{key}:** {val}\n"

    result += "\n"
    return result


def code_block(data: Any, language: str = "json") -> str:
    """JSON code block для отладки (устаревшее — сохранено для совместимости)."""
    if not isinstance(data, str):
        data = json.dumps(data, indent=2, ensure_ascii=False)
    return ""  # Больше не добавляем сырые данные в вывод


def empty_result(tool_name: str, reason: str = "Нет данных") -> str:
    """Вывод для пустого результата инструмента."""
    return (
        f"### ℹ️ `{tool_name}` — **{reason}**\n\n"
        "*Ничего не найдено. Проверьте проект и индекс.*\n"
    )


def error_result(tool_name: str, error: str, start_time: Optional[float] = None) -> str:
    """Вывод для ошибочного результата инструмента."""
    prefix = (
        header(tool_name, "error", start_time)
        if start_time
        else f"### 🔴 `{tool_name}` — **Ошибка**\n\n"
    )
    return prefix + f"```\n{error}\n```\n"


def ok_result(tool_name: str, start_time: float) -> str:
    """Заголовок успешного выполнения."""
    return header(tool_name, "ok", start_time)


# ══════════════════════════════════════════════════════════
# Специализированные форматеры для конкретных инструментов
# ══════════════════════════════════════════════════════════


def format_repo_rank(
    items: List[Dict[str, Any]], execution_time_ms: int, raw: Any
) -> str:
    """Форматирует вывод get_repo_rank по продуктовому стандарту UI."""
    result = (
        f"### 📊 Результат: `get_repo_rank` — **Успешно** (`{execution_time_ms}ms`)\n\n"
    )

    if not items:
        result += "ℹ️ *Ранжирование репозитория не дало результатов.*\n\n"
        return result

    result += "| № | Объект | Вес (Score) | Тип | Файл |\n"
    result += "|---|--------|-------------|-----|------|\n"

    for i, item in enumerate(items, 1):
        symbol = _val(item.get("symbol"), "—")
        score = item.get("score", 0.0)
        kind = _val(item.get("kind"), "—")
        file = _val(item.get("file"), "—")
        result += f"| {i} | **{symbol}** | `{score:.4f}` | `{kind}` | `{file}` |\n"

    result += """

"""
    return result


def format_search_code(
    query: str, results: List[Dict[str, Any]], execution_time_ms: int, mode: str
) -> str:
    """Форматирует вывод search_code."""
    result = f"### 🔍 Результат поиска: `{query}` — **{len(results)} находок** (`{execution_time_ms}ms`, mode={mode})\n\n"

    if not results:
        result += "ℹ️ *Ничего не найдено. Попробуйте другой запрос или mode.*\n"
        return result

    result += "| # | Файл | Строка | Фрагмент | Слой |\n"
    result += "|---|------|--------|----------|------|\n"

    for i, r in enumerate(results[:10], 1):  # топ-10
        file = _val(r.get("file_path", r.get("file", "")), "—")
        line = r.get("start_line", r.get("line", "—"))
        snippet = r.get("text", r.get("snippet", ""))[:80].replace("\n", " ")
        layer = _val(r.get("layer"), "—")
        result += f"| {i} | `{file}` | {line} | `{snippet}` | `{layer}` |\n"

    if len(results) > 10:
        result += f"\n*...и ещё {len(results) - 10} результатов*\n"

    return result


def format_health_report(health: Dict[str, Any], execution_time_ms: int) -> str:
    """Форматирует вывод intel_get_runtime_status / get_health_report."""
    ok = health.get("ok", True)
    icon = "✅" if ok else "🔴"
    result = f"### {icon} Health Report (`{execution_time_ms}ms`)\n\n"

    # Ключевые метрики
    result += key_value(
        [
            ("Проект", _val(health.get("project_path"), "не определён")),
            ("Чанков", health.get("index_telemetry", {}).get("total_chunks", 0)),
            ("Файлов", health.get("index_telemetry", {}).get("unique_files", 0)),
            ("Эмбеддер", health.get("embedding_provider", "неизвестно")),
            ("PID", health.get("resource_usage", {}).get("process_pid", "?")),
        ]
    )

    if not ok:
        errors = health.get("errors", [])
        if errors:
            result += "**Ошибки:**\n"
            for e in errors:
                result += f"- 🔴 {e}\n"
            result += "\n"

    warnings = health.get("warnings", [])
    if warnings:
        result += "**Предупреждения:**"
        for w in warnings:
            result += f"\n- 🟡 {w}"
        result += "\n"

    return result


def format_telemetry(
    counters: Dict[str, Any],
    execution_time_ms: int,
    per_tool: Optional[List[Dict]] = None,
) -> str:
    """Форматирует вывод телеметрии."""
    result = f"### 📊 Телеметрия (`{execution_time_ms}ms`)\n\n"

    # Счётчики
    calls = counters.get("calls", 0)
    errors = counters.get("errors", 0)
    avg_ms = counters.get("avg_ms", 0)

    result += key_value(
        [
            ("Всего вызовов", calls),
            ("Ошибок", errors),
            ("Среднее время", f"{avg_ms}ms"),
            ("RAM (MB)", _val(counters.get("memory_mb"), "N/A")),
        ]
    )

    # Per-tool метрики
    if per_tool:
        rows = []
        for t in per_tool[:15]:
            name = t.get("name", "?")
            tc = t.get("calls", 0)
            t_err = t.get("errors", 0)
            t_avg = t.get("avg_ms", 0)
            rows.append([f"`{name}`", tc, t_err, f"{t_avg}ms"])

        result += table(
            ["Инструмент", "Вызовов", "Ошибок", "Avg ms"],
            rows,
            caption="Поинструментная статистика",
        )

    if per_tool and len(per_tool) > 15:
        result += f"*...и ещё {len(per_tool) - 15} инструментов*\n\n"

    return result


def format_eta(
    operation: str,
    eta_seconds: float,
    confidence: float,
    history_size: int,
) -> str:
    """Форматирует вывод ETAPredictor."""
    icon = "🟢" if confidence > 0.7 else ("🟡" if confidence > 0.4 else "🔴")
    return (
        f"### {icon} ETA: `{operation}`\n\n"
        f"- **Оценка:** {eta_seconds:.0f} сек\n"
        f"- **Уверенность:** {confidence:.0%}\n"
        f"- **История:** {history_size} записей\n"
    )
