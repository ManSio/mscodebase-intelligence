"""tool_help — discoverability without a 69-entry tool surface.

The server registers every tool it has, but the default profile exposes one
entry per intent. This tool answers "what else exists and how do I turn it on"
without putting every variant in the model's tool list.
"""

from __future__ import annotations

import os

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool

_INTENTS = {
    "codebase": "hub: index status, git log/history, write actions (rename/move/delete/replace/insert)",
    "search_code": "ranked code/docs search (FTS5/BM25); start here for 'where is X'",
    "grep_code": "regex search; scope=code skips comments and strings",
    "get_symbol_info": "definition, callers, callees for a symbol",
    "impact_analysis": "what breaks if this symbol changes",
    "graph_query": "graph: related files, variable flow, cypher, impact",
    "read_live_file": "read a line range from disk",
    "notify_change": "tell the index a file changed (after an edit)",
    "get_logs": "recent MCP/server logs",
    "get_health_report": "full diagnostics: index, embedder, resources",
    "intel_get_runtime_status": "one-line runtime status",
    "intel_get_project_memory": "ADRs, incidents, known issues",
    "predict_change": "preview: changed files, affected tests, risk",
    "stale_detector": "documentation drift against the actual version",
}


class ToolHelpTool(MCPTool):
    """tool_help — what this server can do and what is currently exposed."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="tool_help")

    @error_boundary("tool_help", timeout_ms=5000)
    async def execute(self, query: str = "", project_root: str = "") -> str:
        from src.mcp import server_tools as _st

        profile = os.environ.get("MSCODEBASE_MCP_PROFILE", "core").strip().lower()
        catalog = getattr(_st, "_FULL_CATALOG", {}) or {}
        allowlist = {
            item.strip()
            for item in os.environ.get("MSCODEBASE_MCP_TOOLS", "").split(",")
            if item.strip()
        }
        if allowlist:
            # Видимое = то, что реально в листинге: allowlist перекрывает профиль.
            visible = set(catalog) & allowlist
        elif profile == "full":
            visible = set(catalog) or set(_st.CORE_PROFILE)
        else:
            visible = set(_st.CORE_PROFILE) & (set(catalog) or set(_st.CORE_PROFILE))

        label = "allowlist" if allowlist else profile
        lines = [f"🧰 Tool profile: {label} — {len(visible)} exposed"]
        lines.append("")
        for name in sorted(visible):
            desc = catalog.get(name) or _INTENTS.get(name, "")
            lines.append(f"• {name} — {desc}" if desc else f"• {name}")

        hidden = sorted(set(catalog) - visible)
        if hidden:
            lines.append("")
            lines.append(
                f"🔒 {len(hidden)} tools скрыты из списка, но вызываемы по имени. "
                "Схема: tool_help(query=\"<name>\")."
            )
            lines.append("   " + ", ".join(hidden))

        text = "\n".join(lines)
        q = (query or "").strip().lower()
        if q:
            # Schema-on-demand: точное имя инструмента отдаёт его inputSchema,
            # поэтому полная поверхность в tools/list не нужна.
            # Размер поверхности — `python scripts/mcp_surface_size.py`.
            schemas = getattr(_st, "_TOOL_SCHEMAS", {}) or {}
            if q in schemas:
                import json as _json

                desc = catalog.get(q) or _INTENTS.get(q, "")
                head = f"• {q} — {desc}" if desc else f"• {q}"
                hidden_mark = " (скрыт из tools/list; вызов по имени работает)" \
                    if q in hidden else ""
                return f"{head}{hidden_mark}\n\n{_json.dumps({'name': q, 'inputSchema': schemas[q]}, ensure_ascii=False, indent=2)}"

            hits = [
                ln for ln in text.splitlines()
                if q in ln.lower()
            ]
            text = "\n".join(hits) if hits else f"tool_help: no tool matches {query!r}"
        return text
