#!/usr/bin/env python3
"""C2 — РЕАЛЬНЫЙ агрегатор get_edit_context-стиля (эксперимент D, v2).

Не модель: исполняет те же core-инструменты/API, что MCP-сервер, in-process:
- symbols: GetSymbolInfoTool (реальный класс, тот же DI-контейнер)
- impact:  ImpactAnalysisTool (реальный класс)
- git:     GetFileHistoryTool (реальный класс)
- source:  чтение файла вокруг определения (pathlib, реальный диск)
- memory:  IntelligenceStore.load_memory() (реальный JSON-стор памяти проекта)

Состав секций — по классу задачи (intent), как get_ai_context/get_edit_context
у CodeGraph. Время каждой секции — perf_counter (реальный server-side latency).
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.intelligence.store import IntelligenceStore  # noqa: E402

# Какие секции включает каждый класс задачи (intent filter)
INTENT_SECTIONS = {
    "find_bug_cause": ["symbols", "impact", "source", "git"],
    "modify_function": ["symbols", "impact", "source", "git", "memory"],
    "find_impact": ["impact", "symbols", "source"],
    "understand_architecture": ["symbols", "source", "git"],
    "find_test": ["symbols", "memory", "git"],
    "git_history": ["git"],
    "find_caller_callee": ["symbols"],
    "prepare_change": ["symbols", "impact", "source", "git", "memory"],
    "verify_change": ["source", "git"],
}


class EditContextEngine:
    """Реальный агрегатор: 1 вызов → source + symbols + impact + memory + git."""

    def __init__(self, services, project_root: Path):
        self.services = services
        self.project_root = Path(project_root)
        from src.mcp.tools.search_tools import (
            GetSymbolInfoTool,
            ImpactAnalysisTool,
            SearchCodeTool,
        )

        self.symbol_tool = GetSymbolInfoTool(services)
        self.impact_tool = ImpactAnalysisTool(services)
        self.search_tool = SearchCodeTool(services)
        self.store = IntelligenceStore(self.project_root)

    async def _section_symbols(self, symbol: str) -> str:
        out = await self.symbol_tool.execute(query=symbol)
        text = str(out) if not isinstance(out, str) else out
        # Fallback: символ вне графа (inline @mcp.tool, приватные) — gsi пустой,
        # ищем по имени как агент (A-стратегия делает search_code при not-found).
        if ("not found" in text.lower() or "0 callers" in text.lower()
                or "0 usages" in text.lower()):
            try:
                fallback = await self.search_tool.execute(query=symbol, mode="fast", limit=3)
                text += "\n[search fallback] " + str(fallback)[:1200]
            except Exception as e:
                text += f"\n[search fallback error: {e}]"
        return text

    async def _section_impact(self, symbol: str) -> str:
        out = await self.impact_tool.execute(symbol=symbol)
        return str(out) if not isinstance(out, str) else out

    def _section_git(self, file_rel: str) -> str:
        """Реальная git-история файла (тот же источник, что у A-стратегии)."""
        import subprocess

        try:
            r = subprocess.run(
                ["git", "--no-pager", "log", "--oneline", "-6", "--", file_rel],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=15,
            )
            return r.stdout.strip() or f"[git: пусто для {file_rel}]"
        except Exception as e:
            return f"[git error: {e}]"

    def _section_source(self, file_rel: str, symbol: str) -> str:
        """Читает файл: функция/класс, определяющая символ (tool-имя может
        отличаться от def-имени: intel_trigger_reindex → trigger_reindex).
        Pass A: def/class с именем символа. Pass B: слово → walk-DOWN до def
        (декоратор @mcp.tool стоит между функциями — walk-up попадает в чужую)."""
        fp = self.project_root / file_rel
        if not fp.exists():
            return f"[source: {file_rel} не найден]"
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        def_re = re.compile(r"^\s{0,4}(?:async\s+def|def|class)\s+")
        start = None
        for i, ln in enumerate(lines):
            if re.search(rf"^(?:async\s+def|def|class)\s+{re.escape(symbol)}\b", ln.strip()):
                start = i
                break
        if start is None:
            for i, ln in enumerate(lines):
                if re.search(rf"\b{re.escape(symbol)}\b", ln):
                    for j in range(i, len(lines)):  # walk-DOWN: декорированная def
                        if def_re.match(lines[j]):
                            start = j
                            break
                    if start is None:
                        for j in range(i, -1, -1):
                            if def_re.match(lines[j]):
                                start = j
                                break
                    break
        if start is None:
            return f"[source: символ {symbol} не найден в {file_rel}]"
        lo, hi = max(0, start), min(len(lines), start + 80)
        return "\n".join(f"{i + 1}:{lines[i]}" for i in range(lo, hi))

    def _section_memory(self) -> str:
        mem = self.store.load_memory()
        out = []
        for section, nodes in (mem or {}).items():
            for n in (nodes or [])[:8]:
                title = n.get("title") or n.get("name") or str(n)[:80]
                out.append(f"[{section}] {title}")
        return "Project Memory:\n" + "\n".join(out) if out else "Project Memory: <пусто>"

    async def compose(self, symbol: str, file_rel: str, intent: str) -> dict:
        """Собирает контекст. Возвращает payload + реальные тайминги секций."""
        keep = INTENT_SECTIONS.get(intent, ["symbols", "source"])
        parts: dict[str, tuple[str, float]] = {}
        section_texts: dict[str, str] = {}
        for sec in keep:
            t0 = time.perf_counter()
            if sec == "symbols":
                text = await self._section_symbols(symbol)
            elif sec == "impact":
                text = await self._section_impact(symbol)
            elif sec == "git":
                text = self._section_git(file_rel)
            elif sec == "source":
                text = self._section_source(file_rel, symbol)
            elif sec == "memory":
                text = self._section_memory()
            else:
                continue
            parts[sec] = (text, (time.perf_counter() - t0) * 1000)
            section_texts[sec] = text

        sections = {sec: {"ms": ms, "chars": len(txt)} for sec, (txt, ms) in parts.items()}
        payload = "\n\n".join(f"== {sec.upper()} ==\n{txt}" for sec, (txt, _ms) in parts.items())
        total_ms = sum(ms for _t, ms in parts.values())
        return {
            "symbol": symbol,
            "intent": intent,
            "sections": sections,
            "section_texts": section_texts,
            "server_latency_ms": round(total_ms, 2),
            "payload": payload,
            "tokens": round(len(payload) / 4),
        }
