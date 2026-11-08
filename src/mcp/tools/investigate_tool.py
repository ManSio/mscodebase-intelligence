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
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool

_MAX_IDS = 4
_CHANNEL_TIMEOUT = 12.0
_GREP_TIMEOUT = 15.0
_STOPWORDS = {
    "the", "and", "for", "how", "why", "what", "does", "used", "use", "where",
    "when", "which", "with", "from", "into", "that", "this", "files", "file",
    "changed", "change", "checker", "calls", "call", "work", "works", "after",
}


def _memory_hits(nodes: Iterable[Dict[str, Any]], query: str) -> List[str]:
    """Project-memory nodes whose title/body shares a meaningful token."""
    tokens = {t for t in re.findall(r"[a-zа-я0-9_]{5,}", query.lower())}
    if not tokens:
        return []
    hits: List[str] = []
    for node in nodes:
        data = node.get("data") if isinstance(node.get("data"), dict) else node
        title = str(data.get("title") or data.get("name") or node.get("title") or "")
        body = " ".join(
            str(data.get(k) or "") for k in ("description", "content", "text", "summary")
        )
        haystack = (title + " " + body).lower()
        if any(token in haystack for token in tokens):
            label = (title or haystack[:80]).strip()
            if label and label not in hits:
                hits.append(label[:120])
        if len(hits) >= 3:
            break
    return hits


def _identifiers(query: str) -> List[str]:
    """Code-ish tokens from a natural-language question."""
    found: List[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.]{2,}", query):
        token = token.strip(".")
        if not token or token.lower() in _STOPWORDS:
            continue
        if token not in found:
            found.append(token)

    def _score(token: str) -> tuple:
        code_shape = "_" in token or any(c.isupper() for c in token[1:])
        return (1 if code_shape else 0, len(token))

    found.sort(key=_score, reverse=True)
    return found[:_MAX_IDS]


def _merge(items: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Dedup by (file, line); keep the best rank and all channels."""
    merged: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for item in items:
        file = str(item.get("file") or item.get("file_path") or "")
        if not file:
            continue
        line = int(item.get("line") or 0)
        key = (file, line)
        rank = float(item.get("score") or 0.0) + float(item.get("weight") or 0.0)
        current = merged.get(key)
        channels = set(item.get("channels") or [])
        if current is None:
            merged[key] = {
                "file": file,
                "line": line,
                "text": str(item.get("text") or item.get("content") or "")[:200],
                "rank": rank,
                "channels": channels,
            }
        else:
            current["channels"] |= channels
            current["rank"] = max(current["rank"], rank)
            if not current["text"] and item.get("text"):
                current["text"] = str(item["text"])[:200]
    ranked = sorted(
        merged.values(),
        key=lambda r: (len(r["channels"]), r["rank"]),
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
        # Exact-string evidence (2026-11-08). The grep channel is the only one
        # that can say "this identifier occurs in this file". The semantic and
        # symbol channels always answer with neighbours, so without this count
        # an unanswerable question ("where is X implemented", X absent) looks
        # the same as a real answer — the class XERJ ships as a defect (#3021).
        exact: Dict[str, Any] = {"per": {}}

        async def _search() -> None:
            raw = await searcher.hybrid_search_async(query, limit=limit * 2) or []
            for idx, row in enumerate(raw):
                items.append(
                    {
                        "file": row.get("file_path") or row.get("file"),
                        "line": row.get("line") or row.get("start_line") or 0,
                        "text": row.get("text") or row.get("content") or "",
                        "score": row.get("score") or row.get("final_score") or (0.5 - idx * 0.01),
                        "weight": 0.6,
                        "channels": {"search"},
                    }
                )

        def _symbols() -> None:
            for ident in identifiers:
                for ref in (symbol_index.search_symbols(ident, top_k=3) or []):
                    name = getattr(ref, "symbol", "") or getattr(ref, "name", "")
                    file_path = getattr(ref, "file_path", "") or getattr(ref, "file", "")
                    line = int(getattr(ref, "line", 0) or 0)
                    kind = getattr(ref, "kind", "symbol")
                    if not name or not file_path:
                        continue
                    symbol_lines.append(f"• {name} ({kind}) — {file_path}:{line}")
                    items.append(
                        {
                            "file": file_path,
                            "line": line,
                            "text": f"{name} — {kind}",
                            "score": 0.0,
                            "weight": 1.0,
                            "channels": {"symbol"},
                        }
                    )

        def _grep() -> None:
            from src.mcp.tools.grep_tool import GrepCodeTool

            tool = GrepCodeTool(self._services)
            root = Path(self.resolve_indexer(explicit_project_root=_pr).project_path).resolve()
            for ident in identifiers[:2]:
                try:
                    regex = re.compile(re.escape(ident).encode("utf-8"))
                except re.error:
                    continue
                res = tool._search(root, None, regex, "code", limit, 0)  # noqa: SLF001
                matches = res.get("matches", [])
                # `total` (not the truncated list) is the honest count: `limit`
                # would make "3 hits" mean "at most 3". Counted PER identifier:
                # a query like "where is missing_widget implemented" carries
                # the noise word "implemented", and a single sum would hide that
                # the subject itself occurs nowhere.
                exact["per"][ident] = int(res.get("total", len(matches)) or 0)
                for match in matches:
                    items.append(
                        {
                            "file": match["file"],
                            "line": match["line"],
                            "text": match["text"],
                            "score": 0.0,
                            "weight": 0.3,
                            "channels": {"grep"},
                        }
                    )

        async def _run(name: str, func, is_async: bool, timeout: float = _CHANNEL_TIMEOUT) -> None:
            try:
                if is_async:
                    await asyncio.wait_for(func(), timeout=timeout)
                else:
                    await asyncio.wait_for(asyncio.to_thread(func), timeout=timeout)
            except asyncio.TimeoutError:
                degraded.append(f"{name}:timeout")
            except Exception as exc:  # noqa: BLE001 — канал не валит ответ
                degraded.append(f"{name}:{type(exc).__name__}")

        await asyncio.gather(
            _run("search", _search, True),
            _run("symbols", _symbols, False),
            _run("grep", _grep, False, _GREP_TIMEOUT),
        )

        # ─── Pass 2: channels that need a symbol/file from pass 1 ───
        first_pass = _merge(items, 50)
        top_files = [row["file"] for row in first_pass if row["file"]][:3]
        top_names = identifiers[:2]
        root = Path(self.resolve_indexer(explicit_project_root=_pr).project_path).resolve()

        def _impact() -> None:
            for name in top_names:
                res = symbol_index.get_impact_analysis(name, 2) or {}
                cg = res.get("call_graph") or {}
                defs = cg.get("definition") or []
                if isinstance(defs, dict):
                    defs = [defs]
                if not defs:
                    continue
                first = defs[0] if isinstance(defs[0], dict) else {}
                items.append(
                    {
                        "file": first.get("file") or "",
                        "line": first.get("line") or 0,
                        "text": (
                            f"impact {name}: risk={res.get('risk_level', '?')}, "
                            f"affected={len(res.get('affected_files') or [])}"
                        ),
                        "score": 0.0,
                        "weight": 1.2,
                        "channels": {"impact"},
                    }
                )

        def _graph() -> None:
            for name in top_names:
                for caller in (symbol_index.get_callers(name) or [])[:3]:
                    items.append(
                        {
                            "file": getattr(caller, "file_path", "") or getattr(caller, "file", ""),
                            "line": int(getattr(caller, "line", 0) or 0),
                            "text": f"caller of {name}",
                            "score": 0.0,
                            "weight": 1.0,
                            "channels": {"graph"},
                        }
                    )

        def _tests() -> None:
            from src.core.test_impact import predict_affected_tests

            for rel_file in top_files:
                if rel_file.startswith("tests/") or rel_file == "(memory)":
                    continue
                pred = predict_affected_tests([rel_file], str(root)) or {}
                for test in (pred.get("affected_tests") or [])[:3]:
                    items.append(
                        {
                            "file": test,
                            "line": 0,
                            "text": f"covers {rel_file}",
                            "score": 0.0,
                            "weight": 0.1,
                            "channels": {"tests"},
                        }
                    )

        def _memory() -> None:
            from src.core.intelligence.store import IntelligenceStore

            nodes = IntelligenceStore(root)._load_json("project_memory.json")  # noqa: SLF001
            for node in _memory_hits(nodes, query):
                items.append(
                    {
                        "file": "(memory)",
                        "line": 0,
                        "text": node,
                        "score": 0.0,
                        "weight": 0.4,
                        "channels": {"memory"},
                    }
                )

        await asyncio.gather(
            _run("impact", _impact, False),
            _run("graph", _graph, False),
            _run("tests", _tests, False),
            _run("memory", _memory, False),
        )

        merged = _merge(items, limit)
        return self._format(query, identifiers, merged, symbol_lines, degraded, exact)

    def _format(
        self,
        query: str,
        identifiers: List[str],
        merged: List[Dict[str, Any]],
        symbol_lines: List[str],
        degraded: List[str],
        exact: Optional[Dict[str, Any]] = None,
    ) -> str:
        lines = [f"🧭 investigate: `{query}`"]
        if identifiers:
            lines.append(f"   identifiers: {', '.join(identifiers)}")
        lines.append(
            f"   results: {len(merged)}"
            + (f" | degraded: {', '.join(degraded)}" if degraded else "")
        )
        per = {
            str(k): int(v or 0)
            for k, v in ((exact or {}).get("per") or {}).items()
        }
        if per:
            counts = ", ".join(f"{k}={v}" for k, v in list(per.items())[:3])
            subject = next(iter(per))
            if per[subject] == 0 and merged:
                lines.append(
                    f"   ⚠️ exact: {counts} — the first identifier does not occur "
                    "in the indexed code; the results below are neighbours, not "
                    "matches."
                )
            else:
                lines.append(f"   exact: {counts}")
        lines.append("")

        if not merged:
            lines.append("ℹ️ Ничего не найдено. Запрос не подтверждён ни одним каналом.")
            return "\n".join(lines)

        for i, row in enumerate(merged, 1):
            channels = "+".join(sorted(row["channels"]))
            if row["file"] == "(memory)":
                lines.append(f"{i}. [memory] {row['text']}  [{channels}]")
                continue
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
