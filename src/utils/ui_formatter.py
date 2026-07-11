"""
MSCodeBase Intelligence — Визуальный UI-форматтер для MCP-инструментов.

Стиль: приборная панель — прогресс-бары, эмодзи-статусы, узкие карточки.
"""

import json
import time
from typing import Any, Dict, List, Optional

from src.utils.i18n import _


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
    return _("ℹ️ **{name}** — {reason}\n", name=tool_name, reason=reason)


def error_result(tool_name: str, error: str) -> str:
    return _(
        "🔴 **{name}** — Error\n```\n{error}\n```\n",
        name=tool_name,
        error=error,
    )


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
    result = _("{icon} **MSCodeBase** — {status}\n", icon=icon, status=status)
    
    # INC-001 рецидив: если чанки есть, а symbols=0 — SymbolIndex не загрузился
    if symbols == 0 and chunks > 0:
        result += "⚠️ " + _(
            "**SymbolIndex пуст** — символы не проиндексированы. "
            "Переиндексация: `intel_trigger_reindex()`\n"
        )
    
    result += _(
        "📦 **Chunks:** `{chunks}` | **Files:** `{files}` | **Symbols:** `{symbols}`\n",
        chunks=chunks,
        files=files,
        symbols=symbols,
    )
    result += _("🧠 **Embedder:** {embedder}\n", embedder=embedder)

    if other_projects:
        result += _("\n📁 **Другие проекты:**\n")
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
    result = _(
        "🔍 **Search:** `{query}` — **{count}** results ({time}ms, mode={mode})\n\n",
        query=query,
        count=len(results),
        time=exec_ms,
        mode=mode,
    )

    if not results:
        result += _("ℹ️ *Nothing found*\n")
        return result

    for i, r in enumerate(results[:10], 1):
        file = _val(r.get("file_path", r.get("file", "")), "—")
        line = r.get("start_line", r.get("line", "—"))
        layer = _val(r.get("layer"), "—")
        snippet = r.get("text", r.get("snippet", ""))[:300]
        result += f"{i}. 📄 **{file}** (line {line}, {layer})\n"
        if snippet:
            result += f"```\n{snippet}\n```\n"
        result += "\n"

    if len(results) > 10:
        result += _("*...and {more} more*\n", more=len(results) - 10)

    return result


# ══════════════════════════════════════════════════════════
# FORMAT: get_repo_rank
# ══════════════════════════════════════════════════════════


def format_repo_rank(items: List[Dict], exec_ms: int, _raw: Any = None) -> str:
    result = _("🏆 **Symbol Ranking** ({time}ms)\n\n", time=exec_ms)

    if not items:
        result += _("ℹ️ *No data*\n")
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
    """Форматирует статус рантайма в виде дашборда со светофорами.

    🟢 = работает / активно
    🟡 = ожидание / не в приоритете
    ⚪ = отключено / недоступно
    """
    proj = data.get("project_path", "?")
    pid = data.get("resource_usage", {}).get("process_pid", "?")

    # ─── Провайдеры ──────────────────────────────────
    provider = data.get("embedding_provider", "unknown")
    ps = data.get("provider_status", {})
    lm_status = ps.get("lm_studio_at_1234", "offline")
    ollama_status = ps.get("ollama_at_11434", "offline")
    onnx_status = ps.get("onnx_local_engine", "not_found")

    # Светофор: активный = 🟢, доступный но не активный = 🟡, офлайн = ⚪
    lm_led = (
        "🟢"
        if lm_status == "online" and provider == "lm_studio"
        else ("🟡" if lm_status == "online" else "⚪")
    )
    ollama_led = (
        "🟢"
        if ollama_status == "online" and provider == "ollama"
        else ("🟡" if ollama_status == "online" else "⚪")
    )
    # Активный провайдер
    if provider == "llama_cpp":
        llm_led = "🟢"
        llm_name = "llama.cpp (BGE-M3, 1024dim)"
    elif provider == "onnx":
        llm_led = "🟢" if onnx_status == "loaded_and_ready" else "🟡"
        llm_name = "ONNX (bge-m3, 1024dim)"
    else:
        llm_led = "⚪"
        llm_name = f"{provider} (?)"

    # ─── Индекс ──────────────────────────────────────
    tel = data.get("index_telemetry", {})
    chunks = tel.get("total_chunks", 0)
    files = tel.get("unique_files", 0)
    symbols = tel.get("symbol_index_count", tel.get("total_files", 0))
    idx_led = "🟢" if chunks > 1000 else ("🟡" if chunks > 0 else "⚪")

    # ─── Общий статус ─────────────────────────────────
    all_green = provider != "unknown" and chunks > 0
    health_led = "🟢" if all_green else ("🟡" if chunks > 0 else "⚪")

    return _(
        "{hl} **MSCodeBase** — {proj}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🧠 **Embedder**\n"
        "   {llm} {llm_name}\n"
                "   {ll} LM Studio (127.0.0.1:1234)\n"
                "   {oa} Ollama (127.0.0.1:11434)\n"
        "📦 **Index**\n"
        "   {il} {chunks} chunks | {files} files | {symbols} symbols\n"
        "⚙️ **System**\n"
        "   PID: {pid}\n",
        hl=health_led,
        proj=proj,
        llm=llm_led,
        ll=lm_led,
        oa=ollama_led,
        il=idx_led,
        chunks=chunks,
        files=files,
        symbols=symbols,
        pid=pid,
        llm_name=llm_name,
    )


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
    result = _(
        "🖥 **Resources:** RAM {ram:.0f} MB | CPU {cpu:.0f}%\n", ram=ram_mb, cpu=cpu
    )
    result += _(
        "⚡ **LLM:** {model} | ping {ping:.0f}ms | {tps} tok/s\n",
        model=llm_model,
        ping=llm_ping,
        tps=llm_tps,
    )

    if tools:
        result += _("\n📊 **Инструменты:**\n")
        for t in tools[:8]:
            name = t.get("tool", "?")
            calls = t.get("calls", 0)
            avg = t.get("avg_ms", 0)
            err = t.get("errors", 0)
            err_icon = "🔴" if err > 0 else "🟢"
            result += _(
                "   • {name}: {calls} calls, {avg}ms {icon}\n",
                name=name,
                calls=calls,
                avg=avg,
                icon=err_icon,
            )

    if history:
        result += _("\n📅 **История (снэпшоты):**\n")
        for e in history[-7:]:
            d = e.get("date", "?")
            proj = e.get("project", {})
            ch = proj.get("index_chunks", 0)
            res = e.get("resources", {})
            ram = res.get("rss_mb", "—")
            llm_p = e.get("llm", {}).get("ping_ms", "—")
            result += _(
                "   • {d}: {ch} chunks, RAM {ram} MB, LLM {llm}\n",
                d=d,
                ch=ch,
                ram=ram,
                llm=llm_p,
            )

    result += "\n"
    return result


# ══════════════════════════════════════════════════════════
# FORMAT: ETA
# ══════════════════════════════════════════════════════════


def format_eta(operation: str, eta_sec: float, confidence: float, history: int) -> str:
    icon = "🟢" if confidence > 0.7 else ("🟡" if confidence > 0.4 else "🔴")
    bar = _bar(min(confidence, 1.0), 1.0)
    return _(
        "⏱ **ETA:** `{op}`\n"
        "   {bar} `{conf:.0%}`\n"
        "   **Estimate:** {eta:.0f}s | **History:** {hist} records\n\n",
        op=operation,
        bar=bar,
        conf=confidence,
        eta=eta_sec,
        hist=history,
    )


# ══════════════════════════════════════════════════════════
# FORMAT: incidents / memory
# ══════════════════════════════════════════════════════════


def format_incident(component: str, symptom: str, fix: str, incident_id: str) -> str:
    return _(
        "🚨 **{id}**\n"
        "⚙️ **Mod:** `{component}`\n"
        "❌ **Error:** {symptom}\n"
        "🛡️ **Fix:** {fix}\n\n",
        id=incident_id,
        component=component,
        symptom=symptom,
        fix=fix,
    )


def format_project_memory(memory: Dict[str, List]) -> str:
    """Форматирует вывод intel_get_project_memory."""
    result = _("🧠 **Project Memory**\n\n")
    for section, items in memory.items():
        if not items:
            continue
        icons = {
            "adrs": "💡",
            "known_issues": "🐛",
            "tech_debt": "🧹",
            "failed_attempts": "❌",
        }
        icon = icons.get(section, "📌")
        result += _(
            "{icon} **{section}:** {count} entries\n",
            icon=icon,
            section=section.replace("_", " ").title(),
            count=len(items),
        )
        for item in items[:3]:
            data = item.get("data", {})
            title = data.get("title", data.get("issue", data.get("fix", "?")))[:80]
            result += f"   • {title}\n"
        if len(items) > 3:
            result += _("   • ...and {more} more\n", more=len(items) - 3)
        result += "\n"
    return result


def format_hotspots(items: List[Dict]) -> str:
    """Форматирует вывод intel_get_hotspots."""
    result = _("🔥 **Top Risks**\n\n")
    if not items:
        result += _("ℹ️ *No data*\n")
        return result
    for i, item in enumerate(items[:5], 1):
        color = "🔴" if i == 1 else ("🟡" if i <= 3 else "🟢")
        file = item.get("file", "—")
        bugs = item.get("bug_count", 0)
        score = item.get("risk_score", 0)
        result += _(
            "{color} **{file}** — {bugs} bugs (score {score:.2f})\n",
            color=color,
            file=file,
            bugs=bugs,
            score=score,
        )
    result += "\n"
    return result


def format_analysis_result(title: str, data: Dict) -> str:
    """Универсальный форматер для analyze_incident / predict_root_cause."""
    result = _("🔍 **{title}**\n\n", title=title)
    for k, v in data.items():
        if isinstance(v, list):
            if not v:
                continue
            result += _("**{key}:**\n", key=k.replace("_", " ").title())
            for item in v[:5]:
                if isinstance(item, dict):
                    for ik, iv in item.items():
                        result += f"   • {ik}: {str(iv)[:60]}\n"
                else:
                    result += f"   • {item}\n"
            if len(v) > 5:
                result += _("   • ...and {more} more\n", more=len(v) - 5)
        elif isinstance(v, dict):
            result += _("**{key}:**\n", key=k.replace("_", " ").title())
            for ik, iv in v.items():
                result += f"   • {ik}: {str(iv)[:60]}\n"
        else:
            result += f"• {k}: {str(v)[:80]}\n"
        result += "\n"
    return result
