"""get_context — task-shaped инструмент: контекст по нескольким целям одним вызовом (B-scheme).

B-scheme (2026-08-08): intent-фильтр + токен-бюджет + dedup.
Вместо N вызовов get_symbol_info/impact_analysis агент передаёт intent + targets
и получает агрегированный контекст: source + symbols + git + memory + fallback.

Backward compat: targets без intent → explain.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.action_receipt import ActionReceiptStore
from src.core.artifact_paths import get_graph_db_path
from src.core.error_handler import error_boundary
from src.core.graph import EdgeType, PropertyGraph
from src.core.intelligence.store import IntelligenceStore
from src.core.search.graph_adapter import SymbolIndexAdapter
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
    "dataflow": 500,
    "writes": 300,
    "receipts": 400,
    "tests": 300,
}

# Intent → sections mapping (from experiment D v3)
INTENT_SECTIONS = {
    "explain": ["source", "symbols", "git"],
    "modify": ["source", "symbols", "git", "memory", "dataflow", "writes", "receipts", "tests"],
    "debug": ["source", "symbols", "git", "dataflow"],
    "test": ["source", "symbols", "memory", "git", "tests"],
    "git_history": ["source", "symbols", "git"],
    "find_caller_callee": ["symbols"],
    "prepare_change": ["source", "symbols", "git", "memory", "writes", "receipts", "tests"],
    "verify_change": ["source", "symbols", "git", "receipts"],
}

SECTION_PRIORITY = {"source": 5, "symbols": 4, "git": 3, "dataflow": 3, "writes": 3,
                    "receipts": 2, "tests": 2, "memory": 2, "fallback": 1}
_VOR_KEEP = {"VERIFIED", "ACTIVE"}


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
        self._flow_adapter = None

    def _get_flow_adapter(self):
        """Lazy SymbolIndexAdapter over the project PropertyGraph (None = degraded)."""
        if self._flow_adapter is None:
            try:
                pg = PropertyGraph(get_graph_db_path(
                    self._resolve_target_path(None) or Path.cwd()))
                self._flow_adapter = SymbolIndexAdapter(pg)
            except Exception:  # noqa: BLE001
                return None
        return self._flow_adapter

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
            git_data = await self._section_git(target, symbols_data)
            if git_data:
                sections.append(git_data)

        # Dataflow (ASSIGNED_FROM/TO + condition_path, molecule view)
        if "dataflow" in keep_sections and symbols_data:
            dataflow_data = self._section_dataflow(target, symbols_data)
            if dataflow_data:
                sections.append(dataflow_data)

        # Writes (WRITES edges of the target symbol)
        if "writes" in keep_sections and symbols_data:
            writes_data = self._section_writes(symbols_data)
            if writes_data:
                sections.append(writes_data)

        # Memory
        if "memory" in keep_sections:
            memory_data = self._section_memory()
            if memory_data:
                sections.append(memory_data)

        # Receipts (ActionReceipts recorded for the target file)
        if "receipts" in keep_sections and symbols_data:
            receipts_data = self._section_receipts(symbols_data)
            if receipts_data:
                sections.append(receipts_data)

        # Tests (affected tests from impact analysis)
        if "tests" in keep_sections and symbols_data:
            tests_data = self._section_tests(symbols_data)
            if tests_data:
                sections.append(tests_data)

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

        # Structured handoff: downstream sections read meta instead of
        # re-parsing the text with regexes.
        meta: Dict[str, Any] = {}
        if isinstance(sym_result, dict):
            meta["file_path"] = sym_result.get("file") or sym_result.get("file_path")
            meta["line"] = sym_result.get("line")
            meta["symbol"] = sym_result.get("symbol") or target
        else:
            meta["symbol"] = target
        if isinstance(imp_result, dict) and isinstance(imp_result.get("affected_files"), list):
            meta["affected_files"] = imp_result["affected_files"]

        return {
            "name": "symbols",
            "text": full,
            "tokens": len(full) // 4,
            "signature": ("symbols", target),
            "meta": meta,
        }

    def _section_source(self, target: str, symbols_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """source секция: чтение файла вокруг определения символа."""
        # Извлекаем file_path и line из symbols_data текста
        meta = symbols_data.get("meta", {})
        file_path = meta.get("file_path")
        line = meta.get("line")
        if not file_path:
            text = symbols_data.get("text", "")
            match = re.search(r"Definition: `([^`]+)` line (\d+)", text)
            if match:
                file_path = match.group(1)
                line = int(match.group(2))
            else:
                match = re.search(r'"file":\s*"([^"]+)"', text)
                if not match:
                    return None
                file_path = match.group(1)
                line = 1
        line = int(line or 1)

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

    async def _section_git(self, target: str, symbols_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """git секция: последние 6 коммитов по файлу."""
        meta = symbols_data.get("meta", {})
        file_path = meta.get("file_path")
        if not file_path:
            text = symbols_data.get("text", "")
            match = re.search(r'"affected_files":\s*\[\s*"([^"]+)"', text)
            if not match:
                match = re.search(r'"file":\s*"([^"]+)"', text)
            if not match:
                match = re.search(r'Definition: `([^`]+)` line', text)
            if not match:
                return None
            file_path = match.group(1)

        try:
            project_root = self._resolve_target_path(None) or Path.cwd()
            r = await asyncio.to_thread(
                subprocess.run,
                ["git", "--no-pager", "log", "--oneline", "-6", "--", file_path],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
                shown = 0
                for n in (nodes or []):
                    if shown >= 8:
                        break
                    status = n.get("status")
                    if status and status not in _VOR_KEEP:
                        continue  # REFUTED/INCONCLUSIVE/STALE are not shown (VOR)
                    title = n.get("title") or n.get("name") or str(n)[:80]
                    out_lines.append(f"  [{section}] {title}")
                    shown += 1
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

    def _section_dataflow(self, target: str, symbols_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """dataflow section: ASSIGNED_FROM/TO chains + condition_path for local
        variables of the target file (deterministic, no LLM)."""
        ga = self._get_flow_adapter()
        if ga is None:
            return None
        meta = symbols_data.get("meta", {})
        file_path = meta.get("file_path")
        if not file_path:
            return None
        try:
            fp = Path(file_path)
            if not fp.exists():
                return None
            window = "\n".join(
                fp.read_text(encoding="utf-8", errors="replace").splitlines()[:400])
        except Exception:  # noqa: BLE001
            return None

        candidates: List[str] = []
        for m in re.finditer(r"^\s{4,}(\w+)\s*=[^=]", window, re.MULTILINE):
            name = m.group(1)
            if name in ("self", "cls") or name in candidates:
                continue
            candidates.append(name)
            if len(candidates) >= 3:
                break
        if not candidates:
            return None

        out_lines: List[str] = []
        for var in candidates:
            try:
                flow = ga.get_variable_flow(var, file_path=str(file_path), max_depth=2)
            except Exception:  # noqa: BLE001
                continue
            if not flow.get("variable"):
                continue
            out_lines.append(f"{var}: {flow['variable'].get('qualified_name', '?')}")
            for step in (flow.get("chain") or [])[:4]:
                cond = step.get("condition_path") or []
                cond_s = f"  [if: {' & '.join(map(str, cond))}]" if cond else ""
                out_lines.append(f"  <- {step.get('via', '?')} (line {step.get('line', '?')}){cond_s}")
            if len(out_lines) >= 12:
                break
        if not out_lines:
            return None
        text = "\n".join(out_lines)
        return {"name": "dataflow", "text": text, "tokens": len(text) // 4,
                "signature": ("dataflow", target)}

    def _section_writes(self, symbols_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """writes section: WRITES edges of the target symbol from PropertyGraph."""
        ga = self._get_flow_adapter()
        if ga is None:
            return None
        meta = symbols_data.get("meta", {})
        file_path = meta.get("file_path")
        symbol_name = meta.get("symbol")
        if not file_path or not symbol_name:
            return None
        base = f"D:.{Path(file_path).as_posix()}"
        lines: List[str] = []
        try:
            for qname in (f"{base}.{symbol_name}", base):
                nb = ga._graph.get_neighbors(qname, edge_type=EdgeType.WRITES,
                                             direction="outgoing", max_depth=1)
                for node, edge, depth in nb[:10]:
                    lines.append(f"  -> {getattr(node, 'qualified_name', '?')}")
                if lines:
                    break
        except Exception:  # noqa: BLE001
            return None
        if not lines:
            return None
        text = "WRITES:\n" + "\n".join(lines)
        return {"name": "writes", "text": text, "tokens": len(text) // 4,
                "signature": ("writes", file_path)}

    def _section_receipts(self, symbols_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """receipts section: recent ActionReceipts recorded for the target file."""
        meta = symbols_data.get("meta", {})
        file_path = meta.get("file_path")
        if not file_path:
            return None
        try:
            project_root = self._resolve_target_path(None) or Path.cwd()
            entries = ActionReceiptStore(project_root).query(limit=100)
        except Exception as e:  # noqa: BLE001
            entries = []
            err = f"[receipts error: {e}]"
        else:
            err = None
        fp_norm = str(file_path).replace("\\", "/")
        hits: List[Dict[str, Any]] = []
        for e in entries:
            for k in ("file_path", "file", "target_file", "path"):
                v = str(e.get(k, "")).replace("\\", "/")
                if v and (v.endswith(fp_norm) or fp_norm.endswith(v)):
                    hits.append(e)
                    break
            if len(hits) >= 6:
                break
        if not hits:
            return None
        lines = ["Receipts:"] + [
            f"  {e.get('action_type', '?')} {e.get('verdict', '?')} {str(e.get('ts', ''))[:19]}"
            for e in hits]
        if err:
            lines.append(err)
        text = "\n".join(lines)
        return {"name": "receipts", "text": text, "tokens": len(text) // 4,
                "signature": ("receipts", file_path)}

    def _section_tests(self, symbols_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """tests section: affected tests from impact analysis affected_files."""
        meta = symbols_data.get("meta", {})
        affected = meta.get("affected_files") or []
        tests = [f for f in affected if "test_" in f or f.endswith("_test.py")][:8]
        if not tests:
            return None
        text = "Affected tests:\n" + "\n".join(f"  {t}" for t in tests)
        return {"name": "tests", "text": text, "tokens": len(text) // 4,
                "signature": ("tests", tests[0])}

