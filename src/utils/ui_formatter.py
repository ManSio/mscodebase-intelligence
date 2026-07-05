"""
MSCodeBase Intelligence — Визуальный UI-форматтер для MCP-инструментов.

Стиль: приборная панель — прогресс-бары, эмодзи-статусы, узкие карточки.
"""

import json
import time
from typing import Any, Dict, List, Optional


def _bar(value: float, max_val: float, width: int = 15) -> str:
    """Прогресс-бар: [████░░░░░░░░░░░] (15 символов)"""
    filled = max(0, min(width, int((value / max_val) * width)))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def _val(val: Any, default: str = "—") -> str:
    if val is None or val == "unknown" or val == "":
        return default
    return str(val)


def _status_icon(status: str) -> str:
    return {"ok": "🟢", "warn": "🟡", "error": "🔴", "info": "ℹ️"}.get(status, "🟢")


def header(tool_name: str, status: str = "ok", extra: Optional[str] = None) -> str:
    icon = _status_icon(status)
    return f"{icon} **{tool_name}**" + (f" — {extra}" if extra else "") + "\n"


def section(title: str) -> str:
    """Разделитель секции."""
    return f"\n{title}\n{'━' * 30}\n"


def empty_result(tool_name: str, reason: str = "Нет данных") -> str:
    return f"ℹ️ **{tool_name}** — {reason}\n"


def error_result(tool_name: str, error: str) -> str:
    return f"🔴 **{tool_name}** — Ошибка\n```\n{error}\n```\n"


# ══════════════════════════════════════════════════════════
# FORMAT: get_index_status
# ══════════════════════════════════════════════════════════


def format_index_status(
    chunks: int,
    files: int,
    symbols: int,
    embedder: str,
    status: str,
    other_projects: Optional[List[str]] = None,
) -> str:
    icon = "🟢" if chunks > 0 else "🟡"
    result = f"{icon} **MSCodeBase** — {status}\n"
    result += (
        f"📦 **Чанки:** `{chunks}` | **Файлы:** `{files}` | **Символы:** `{symbols}`\n"
    )
    result += f"🧠 **Эмбеддер:** {embedder}\n"

    if other_projects:
        result += f"\n📁 **Другие проекты:**\n"
        for p in other_projects:
            result += f"   • `{p}`\n"

    result += "\n"
    return result


# ══════════════════════════════════════════════════════════
# FORMAT: search_code
# ══════════════════════════════════════════════════════════


def format_search_code(
    query: str, results: List[Dict[str, Any]], exec_ms: int, mode: str
) -> str:
    result = f"🔍 **Поиск:** `{query}` — **{len(results)}** находок ({exec_ms}ms, mode={mode})\n\n"

    if not results:
        result += "ℹ️ *Ничего не найдено*\n"
        return result

    for i, r in enumerate(results[:10], 1):
        file = _val(r.get("file_path", r.get("file", "")), "—")
        line = r.get("start_line", r.get("line", "—"))
        layer = _val(r.get("layer"), "—")
        snippet = r.get("text", r.get("snippet", ""))[:300]
        result += f"{i}. 📄 **{file}** (стр. {line}, {layer})\n"
        if snippet:
            result += f"```\n{snippet}\n```\n"
        result += "\n"

    if len(results) > 10:
        result += f"*...и ещё {len(results) - 10}*\n"

    return result


# ══════════════════════════════════════════════════════════
# FORMAT: get_repo_rank
# ══════════════════════════════════════════════════════════


def format_repo_rank(items: List[Dict], exec_ms: int, _raw: Any = None) -> str:
    result = f"🏆 **Рейтинг символов** ({exec_ms}ms)\n\n"

    if not items:
        result += "ℹ️ *Нет данных*\n"
        return result

    for i, item in enumerate(items[:10], 1):
        symbol = _val(item.get("symbol"), "—")
        score = item.get("score", 0)
        kind = _val(item.get("kind"), "—")
        file = _val(item.get("file"), "—")
        risk = "🔴" if score > 0.8 else ("🟡" if score > 0.5 else "🟢")
        result += f"{risk} **{symbol}** — `{score:.4f}`\n"
        result += f"   📁 {file} | 🏷 {kind}\n"

    result += "\n"
    return result


# ══════════════════════════════════════════════════════════
# FORMAT: intel_get_runtime_status / get_health_report
# ══════════════════════════════════════════════════════════


def format_runtime_status(data: Dict[str, Any]) -> str:
    proj = data.get("project_path", "?")
    chunks = data.get("index_telemetry", {}).get("total_chunks", 0)
    files = data.get("index_telemetry", {}).get("unique_files", 0)
    pid = data.get("resource_usage", {}).get("process_pid", "?")
    embedder = data.get("embedding_provider", "?")
    lm = data.get("provider_status", {}).get("lm_studio_at_1234", "offline")
    lm_icon = "🟢" if lm == "online" else ("🟡" if lm == "offline" else "🔴")
    status = data.get("index_telemetry", {}).get("status", "?")
    status_icon = "🟢" if status == "active" else "🟡"

    result = f"{status_icon} **MSCodeBase** — {proj}\n"
    result += f"📦 **Чанки:** {chunks} | **Файлы:** {files}\n"
    result += f"🧠 **Эмбеддер:** {embedder} | {lm_icon} LM Studio: {lm}\n"
    result += f"⚙️ **PID:** {pid}\n"
    return result


# ══════════════════════════════════════════════════════════
# FORMAT: intel_get_telemetry
# ══════════════════════════════════════════════════════════


def format_telemetry(
    ram_mb: float,
    cpu: float,
    llm_model: str,
    llm_ping: float,
    llm_tps: int,
    tools: List[Dict],
    history: Optional[List[Dict]] = None,
) -> str:
    result = f"🖥 **Ресурсы:** RAM {ram_mb:.0f} MB | CPU {cpu:.0f}%\n"
    result += f"⚡ **LLM:** {llm_model} | ping {llm_ping:.0f}ms | {llm_tps} tok/s\n"

    if tools:
        result += f"\n📊 **Инструменты:**\n"
        for t in tools[:8]:
            name = t.get("tool", "?")
            calls = t.get("calls", 0)
            avg = t.get("avg_ms", 0)
            err = t.get("errors", 0)
            err_icon = "🔴" if err > 0 else "🟢"
            result += f"   • {name}: {calls} вызовов, {avg}ms {err_icon}\n"

    if history:
        result += f"\n📅 **История (снэпшоты):**\n"
        for e in history[-7:]:
            d = e.get("date", "?")
            proj = e.get("project", {})
            ch = proj.get("index_chunks", 0)
            res = e.get("resources", {})
            ram = res.get("rss_mb", "—")
            llm_p = e.get("llm", {}).get("ping_ms", "—")
            result += f"   • {d}: {ch} чанков, RAM {ram} MB, LLM {llm_p}\n"

    result += "\n"
    return result


# ══════════════════════════════════════════════════════════
# FORMAT: hotpots
# ══════════════════════════════════════════════════════════


def format_hotspots(items: List[Dict]) -> str:
    result = "🔥 **Топ рисков**\n\n"
    if not items:
        result += "ℹ️ *Нет данных*\n"
        return result

    risk_colors = ["🔴", "🟡", "🟢"]
    for i, item in enumerate(items[:5]):
        color = risk_colors[min(i, 2)]
        file = _val(item.get("file"), "—")
        bugs = item.get("bug_count", 0)
        result += f"{color} **{file}** — {bugs} багов\n"

    result += "\n"
    return result


# ══════════════════════════════════════════════════════════
# FORMAT: ETA
# ══════════════════════════════════════════════════════════


def format_eta(operation: str, eta_sec: float, confidence: float, history: int) -> str:
    icon = "🟢" if confidence > 0.7 else ("🟡" if confidence > 0.4 else "🔴")
    bar = _bar(min(confidence, 1.0), 1.0)
    return (
        f"⏱ **ETA:** `{operation}`\n"
        f"   {bar} `{confidence:.0%}`\n"
        f"   **Оценка:** {eta_sec:.0f}с | **История:** {history} зап.\n\n"
    )


# ══════════════════════════════════════════════════════════
# FORMAT: incidents / memory
# ══════════════════════════════════════════════════════════


def format_incident(component: str, symptom: str, fix: str, incident_id: str) -> str:
    return (
        f"🚨 **{incident_id}**\n"
        f"⚙️ **Mod:** `{component}`\n"
        f"❌ **Error:** {symptom}\n"
        f"🛡️ **Fix:** {fix}\n\n"
    )
