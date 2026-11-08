"""investigate — one query in, parallel fan-out out.

The agent should formulate a question, not choose between 54 tools. This tool
runs every relevant channel concurrently and merges the answers with
provenance:

    search  — ranked FTS5/BM25 over code and docs
    symbols — exact/prefix symbol matches
    grep    — regex over identifiers, AST-scoped (comments/strings skipped)

Each channel has its own timeout: a slow one degrades the answer instead of
failing it (`degraded: [...]`). Duplicates are merged by (file, line) and every
item keeps the set of channels that found it, so the evidence is auditable.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool

_MAX_IDS = 3
_CHANNEL_TIMEOUT = 8.0


def _identifiers(query: str) -> List[str]:
    """Code-ish tokens from a natural-language question."""
    found: List[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.]{2,}", query):
        token = token.strip(".")
        if not token or token.lower() in {"the", "and", "how", "why", "what", "does"}:
            continue
        if token not in found:
            found.append(token)
    # CamelCase / snake_case first — they are the likeliest symbol names.
    found.sort(key=lambda t: (not ("_" in t or any(c.isupper() for c in t[1:])), t))
    return found[:_MAX_IDS]


def _merge(items: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Dedup by (file, line); keep the best score and all channels."""
    merged: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for item in items:
        file = str(item.get("file") or item.get("file_path") or "")
        if not file:
            continue
        line = int(item.get("line") or 0)
        key = (file, line)
        current = merged.get(key)
        channels = set(item.get("channels") or [])
        if current is None:
            merged[key] = {
                "file": file,
                "line": line,
                "text": str(item.get("text") or item.get("content") or "")[:200],
                "score": float(item.get("score") or 0.0),
                "channels": channels,
            }
        else:
            current["channels"] |= channels
            current["score"] = max(current["score"], float(item.get("score") or 0.0))
            if not current["text"] and item.get("text"):
                current["text"] = str(item.get("text"))[:200]
    ranked = sorted(
        merged.values(),
        key=lambda r: (len(r["channels"]), r["score"]),
        reverse=True,
    )
    return ranked[:limit]


class InvestigateTool(MCPTool):
    """investigate — one question, all channels, one answer."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="investigate")

    @error_boundary("investigate", timeout_ms=30000)
    async def execute(
        self,
        query: str,
        limit: int = 8,
        project_root: str = "",
    ) -> str:
        query = (query or "").strip()
        if not query:
            return "❌ investigate: пустой запрос"
        _pr = project_root or None
        await self.require_ready_project(explicit_project_root=_pr)
        limit = max(3, min(int(limit), 20))

        identifiers = _identifiers(query)
        searcher = self.resolve_searcher(explicit_project_root=_pr)
        symbol_index = self.resolve_symbol_index(explicit_project_root=_pr)

        degraded: List[str] = []
        items: List[Dict[str, Any]] = []
        symbol_lines: List[str] = []

        async def _search() -> None:
            raw = await searcher.hybrid_search_async(query, limit=limit * 2)
            for row in raw or []:
                items.append(
                    {
                        "file": row.get("file_path") or row.get("file"),
                        "line": row.get("line") or row.get("start_line") or 0,
                        "text": row.get("text") or row.get("content") or "",
                        "score": row.get("score") or row.get("final_score") or 0.0,
                        "channels": {"search"},
                    }
                )

        def _symbols() -> None:
            for ident in identifiers:
                refs = symbol_index.search_symbols(ident, top_k=3) or []
                for ref in refs:
                    symbol_lines.append(
                        f"• {ref.name} ({getattr(ref, 'kind', '?')}) — "
                        f"{ref.file}:{getattr(ref, 'line', 0)}"
                    )
                    items.append(
                        {
                            "file": ref.file,
                            "line": getattr(ref, "line", 0),
                            "text": f"{ref.name} — {getattr(ref, 'kind', 'symbol')}",
                            "score": 1.0,
                            "channels": {"symbol"},
                        }
                    )

        def _grep() -> None:
            from src.mcp.tools.grep_tool import GrepCodeTool

            tool = GrepCodeTool(self._services)
            root = Path(self.resolve_indexer(explicit_project_root=_pr).project_path).resolve()
            for ident in identifiers:
                try:
                    regex = re.compile(re.escape(ident).encode("utf-8"))
                except re.error:
                    continue
                res = tool._search(root, None, regex, "code", limit, 0)  # noqa: SLF001
                for match in res.get("matches", []):
                    items.append(
                        {
                            "file": match["file"],
                            "line": match["line"],
                            "text": match["text"],
                            "score": 0.5,
                            "channels": {"grep"},
                        }
                    )

        async def _run(name: str, func, is_async: bool) -> None:
            try:
                if is_async:
                    await asyncio.wait_for(func(), timeout=_CHANNEL_TIMEOUT)
                else:
                    await asyncio.wait_for(
                        asyncio.to_thread(func), timeout=_CHANNEL_TIMEOUT
                    )
            except asyncio.TimeoutError:
                degraded.append(f"{name}:timeout")
            except Exception as exc:  # noqa: BLE001 — канал не валит ответ
                degraded.append(f"{name}:{type(exc).__name__}")

        await asyncio.gather(
            _run("search", _search, True),
            _run("symbols", _symbols, False),
            _run("grep", _grep, False),
        )

        merged = _merge(items, limit)
        return self._format(query, identifiers, merged, symbol_lines, degraded)

    def _format(
        self,
        query: str,
        identifiers: List[str],
        merged: List[Dict[str, Any]],
        symbol_lines: List[str],
        degraded: List[str],
    ) -> str:
        lines = [f"🧭 investigate: `{query}`"]
        if identifiers:
            lines.append(f"   identifiers: {', '.join(identifiers)}")
        lines.append(
            f"   results: {len(merged)}"
            + (f" | degraded: {', '.join(degraded)}" if degraded else "")
        )
        lines.append("")

        if not merged:
            lines.append("ℹ️ Ничего не найдено. Запрос не подтверждён ни одним каналом.")
            return "\n".join(lines)

        for i, row in enumerate(merged, 1):
            channels = "+".join(sorted(row["channels"]))
            lines.append(f"{i}. {row['file']}:{row['line']}  [{channels}]")
            if row["text"]:
                lines.append(f"   {row['text'].strip()[:180]}")

        if symbol_lines:
            lines.append("")
            lines.append("Символы:")
            lines.extend(symbol_lines[:6])

        first = merged[0]
        lines.append("")
        lines.append(
            f"Дальше: get_symbol_info(\"{identifiers[0] if identifiers else ''}\") "
            f"| impact_analysis | read_live_file(\"{first['file']}\")"
        )
        return "\n".join(lines)
