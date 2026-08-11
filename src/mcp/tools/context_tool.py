"""get_context — task-shaped инструмент: контекст по нескольким целям одним вызовом (B-scheme).

B-scheme (2026-08-08): intent-фильтр + токен-бюджет + dedup.
Вместо N вызовов get_symbol_info/impact_analysis агент передаёт intent + targets
и получает агрегированный контекст: source + symbols + git + memory + fallback.

Backward compat: targets без intent → explain.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.error_handler import error_boundary
from src.core.intelligence.store import IntelligenceStore
from src.mcp.tools.base import MCPTool
from src.mcp.tools.search_tools import GetSymbolInfoTool, ImpactAnalysisTool, SearchCodeTool

_MAX_TARGETS = 10
TOKEN_LIMIT = 2000
SECTION_BUDGETS = {
    "source": 1200,
    "symbols": 800,
    "git": 300,
    "memory": 400,
    "fallback": 200,
}

# Intent → sections mapping (from experiment D v3)
INTENT_SECTIONS = {
    "explain": ["source", "symbols", "git"],
    "modify": ["source", "symbols", "git", "memory"],
    "debug": ["source", "symbols", "git"],
    "test": ["source", "symbols", "memory", "git"],
    "git_history": ["source", "symbols", "git"],
    "find_caller_callee": ["symbols"],
    "prepare_change": ["source", "symbols", "git", "memory"],
    "verify_change": ["source", "symbols", "git"],
}

SECTION_PRIORITY = {"source": 5, "symbols": 4, "git": 3, "memory": 2, "fallback": 1}


def _truncate_to_budget(text: str, budget: int) -> str:
    """Обрезает текст до бюджета токенов (chars/4)."""
    max_chars = budget * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def _dedup_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Удаляет дубликаты секций по (file_path, symbol_name), оставляет высший приоритет."""
    seen = {}
    for sec in sections:
        key = sec.get("signature")
        if not key:
            continue
        prio = SECTION_PRIORITY.get(sec["name"], 0)
        if key not in seen or prio > seen[key][1]:
            seen[key] = (sec, prio)
    return [v[0] for v in seen.values()]


class GetContextTool(MCPTool):
    """get_context — агрегированный контекст для символов (B-scheme: intent-фильтр, токен-бюджет, dedup)."""

    def __init__(self, services):
        super().__init__(services, tool_name="get_context")
        self._store = IntelligenceStore(self._resolve_target_path(None) or Path.cwd())

    @error_boundary("get_context", timeout_ms=30000)
    async def execute(
        self,
        targets: Optional[List[str]] = None,
        intent: str = "explain",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """
        targets: список символов (backward compat)
        intent: explain|modify|debug|test|git_history|find_caller_callee|prepare_change|verify_change
        kwargs: legacy targets через kwargs.get("targets")
        """
        _kwargs = kwargs or {}
        targets = targets if targets is not None else _kwargs.get("targets", [])
        if isinstance(targets, str):
            targets = [t.strip() for t in targets.split(",") if t.strip()]
        targets = [t for t in targets if t][:_MAX_TARGETS]

        if not targets:
            return {
                "status": "error",
                "message": (
                    "targets обязателен: get_context(targets=['Indexer', 'Searcher'], "
                    "intent='modify')"
                ),
            }

        # Валидация intent
        if intent not in INTENT_SECTIONS:
            return {
                "status": "error",
                "message": f"Unknown intent '{intent}'. Available: {', '.join(INTENT_SECTIONS)}",
            }

        keep_sections = INTENT_SECTIONS[intent]

        # Инициализируем инструменты
        symbol_tool = GetSymbolInfoTool(self._services)
        impact_tool = ImpactAnalysisTool(self._services)
        search_tool = SearchCodeTool(self._services)

        # Собираем секции для каждого target
        results: Dict[str, Any] = {}
        for target in targets:
            sections = await self._collect_sections(
                target, keep_sections, symbol_tool, impact_tool, search_tool
            )

            # Dedup + token budget
            sections = _dedup_sections(sections)
            sections = self._apply_token_budget(sections)

            payload = "\n\n".join(
                f"== {sec['name'].upper()} ==\n{sec['text']}" for sec in sections
            )
            results[target] = {
                "sections": [{"name": s["name"], "tokens": s["tokens"]} for s in sections],
                "payload": payload,
                "total_tokens": sum(s["tokens"] for s in sections),
            }

        return {
            "status": "ok",
            "targets": targets,
            "intent": intent,
            "total_targets": len(targets),
            "context": results,
        }

    async def _collect_sections(
        self,
        target: str,
        keep_sections: List[str],
        symbol_tool: GetSymbolInfoTool,
        impact_tool: ImpactAnalysisTool,
        search_tool: SearchCodeTool,
    ) -> List[Dict[str, Any]]:
        """Собирает все секции для одного target."""
        sections = []

        # Сначала symbols (нужен для source/git path)
        symbols_data = None
        if "symbols" in keep_sections:
            symbols_data = await self._section_symbols(target, symbol_tool, impact_tool, search_tool)
            if symbols_data:
                sections.append(symbols_data)

        # Source (нужен file_path из symbols)
        if "source" in keep_sections and symbols_data:
            source_data = self._section_source(target, symbols_data)
            if source_data:
                sections.append(source_data)

        # Git (нужен file_path из symbols)
        if "git" in keep_sections and symbols_data:
            git_data = self._section_git(target, symbols_data)
            if git_data:
                sections.append(git_data)

        # Memory
        if "memory" in keep_sections:
            memory_data = self._section_memory()
            if memory_data:
                sections.append(memory_data)

        # Fallback (если symbols не дали definition)
        if "fallback" in keep_sections and symbols_data:
            fallback_data = self._section_fallback(target, symbols_data, search_tool)
            if fallback_data:
                sections.append(fallback_data)

        return sections

    async def _section_symbols(
        self, target: str, symbol_tool: GetSymbolInfoTool, impact_tool: ImpactAnalysisTool, search_tool: SearchCodeTool
    ) -> Optional[Dict[str, Any]]:
        """symbols секция: GetSymbolInfoTool + impact + fallback search_code."""
        try:
            sym_result = await symbol_tool.execute(target)
            imp_result = await impact_tool.execute(target)
        except Exception as e:  # noqa: BLE001
            return {"name": "symbols", "text": f"Error: {e}", "tokens": 0, "signature": None}

        # Парсим symbol_info (string) и impact (dict или string)
        text_parts = []
        if isinstance(sym_result, str):
            text_parts.append(sym_result)
        elif isinstance(sym_result, dict):
            text_parts.append(json.dumps(sym_result, ensure_ascii=False, indent=2))
        if isinstance(imp_result, str):
            text_parts.append(imp_result)
        elif isinstance(imp_result, dict):
            text_parts.append(json.dumps(imp_result, ensure_ascii=False, indent=2))

        # Fallback search_code если definition пустой
        has_def = "Definition:" in sym_result or "definition" in str(sym_result).lower()
        if not has_def:
            try:
                fb = await search_tool.execute(query=target, mode="fast", limit=3)
                text_parts.append("[search fallback] " + str(fb)[:1200])
            except Exception:  # noqa: BLE001
                pass

        full = "\n".join(text_parts)
        return {
            "name": "symbols",
            "text": full,
            "tokens": len(full) // 4,
            "signature": ("symbols", target),
        }

    def _section_source(self, target: str, symbols_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """source секция: чтение файла вокруг определения символа."""
        # Извлекаем file_path и line из symbols_data текста
        text = symbols_data.get("text", "")
        match = re.search(r"Definition: `([^`]+)` line (\d+)", text)
        if not match:
            # Пробуем из impact
            match = re.search(r'"file":\s*"([^"]+)"', text)
            if not match:
                return None
            file_path = match.group(1)
            line = 1
        else:
            file_path = match.group(1)
            line = int(match.group(2))

        # Читаем файл
        try:
            fp = Path(file_path)
            if not fp.exists():
                return {"name": "source", "text": f"[source: {file_path} not found]", "tokens": 0, "signature": ("source", file_path)}

            lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(0, line - 1 - 15)
            end = min(len(lines), line - 1 + 30)
            snippet = "\n".join(f"{i+1}:{lines[i]}" for i in range(start, end))
        except Exception as e:  # noqa: BLE001
            snippet = f"[source error: {e}]"

        return {
            "name": "source",
            "text": snippet,
            "tokens": len(snippet) // 4,
            "signature": ("source", file_path),
        }

    def _section_git(self, target: str, symbols_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """git секция: последние 6 коммитов по файлу."""
        text = symbols_data.get("text", "")
        # Сначала пробуем из impact (affected_files)
        match = re.search(r'"affected_files":\s*\[\s*"([^"]+)"', text)
        if not match:
            # Fallback: пробуем file из definition
            match = re.search(r'"file":\s*"([^"]+)"', text)
        if not match:
            # Fallback: Definition: `file` line
            match = re.search(r'Definition: `([^`]+)` line', text)
        if not match:
            return None
        file_path = match.group(1)

        try:
            project_root = self._resolve_target_path(None) or Path.cwd()
            r = subprocess.run(
                ["git", "--no-pager", "log", "--oneline", "-6", "--", file_path],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=15,
            )
            out = r.stdout.strip()
            snippet = out or f"[git: no history for {file_path}]"
        except Exception as e:  # noqa: BLE001
            snippet = f"[git error: {e}]"

        return {
            "name": "git",
            "text": snippet,
            "tokens": len(snippet) // 4,
            "signature": ("git", file_path),
        }

    def _section_memory(self) -> Optional[Dict[str, Any]]:
        """memory секция: топ-8 узлов из project memory."""
        try:
            mem = self._store.load_memory()
            out_lines = ["Project Memory:"]
            for section, nodes in (mem or {}).items():
                for n in (nodes or [])[:8]:
                    title = n.get("title") or n.get("name") or str(n)[:80]
                    out_lines.append(f"  [{section}] {title}")
            snippet = "\n".join(out_lines)
        except Exception as e:  # noqa: BLE001
            snippet = f"[memory error: {e}]"

        return {
            "name": "memory",
            "text": snippet,
            "tokens": len(snippet) // 4,
            "signature": ("memory", "project"),
        }

    async def _section_fallback(
        self, target: str, symbols_data: Dict[str, Any], search_tool: SearchCodeTool
    ) -> Optional[Dict[str, Any]]:
        """fallback секция: search_code для символов вне графа."""
        text = symbols_data.get("text", "")
        has_def = "Definition:" in text or "definition" in text.lower()
        if has_def:
            return None

        try:
            fb = await search_tool.execute(query=target, mode="fast", limit=3)
            snippet = "[search fallback] " + str(fb)[:1200]
        except Exception as e:  # noqa: BLE001
            snippet = f"[fallback error: {e}]"

        return {
            "name": "fallback",
            "text": snippet,
            "tokens": len(snippet) // 4,
            "signature": ("fallback", target),
        }

    def _apply_token_budget(self, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Применяет токен-бюджет: hard-limit TOKEN_LIMIT, пропорционально урезает низкоприоритетные."""
        total = sum(s["tokens"] for s in sections)
        if total <= TOKEN_LIMIT:
            return sections

        # Сортируем по приоритету (низкий -> высокий)
        sections.sort(key=lambda s: SECTION_PRIORITY.get(s["name"], 0))
        excess = total - TOKEN_LIMIT

        for sec in sections:
            if excess <= 0:
                break
            budget = SECTION_BUDGETS.get(sec["name"], 0)
            if sec["tokens"] <= budget:
                continue
            cut = min(excess, sec["tokens"] - budget)
            sec["tokens"] -= cut
            # Обрезаем текст
            sec["text"] = _truncate_to_budget(sec["text"], sec["tokens"])
            excess -= cut

        # Восстанавливаем порядок приоритета
        sections.sort(key=lambda s: -SECTION_PRIORITY.get(s["name"], 0))
        return sections

