"""Поисковые инструменты: search_code, get_symbol_info, impact_analysis.

ИСПРАВЛЕНО (v2):
- _auto_search: заменена русская грамматическая эвристика на токен-базированную
- Добавлена поддержка английских индикаторов сложности
- search_code возвращает JSON с полями status + results
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import IndexNotReadyError, error_boundary
from src.core.indexer import Indexer
from src.core.searcher import Searcher
from src.core.symbol_index import SymbolIndex
from src.mcp.tools.base import MCPTool
from src.utils.ui_formatter import format_search_code

logger = logging.getLogger("mscodebase_server.search_tools")


# ══════════════════════════════════════════════════════════
# Эвристика сложности запроса (исправлена)
# ══════════════════════════════════════════════════════════


def _is_complex_query(query: str) -> bool:
    """Определяет, нужен ли Agentic Search (vs простой векторный).

    ★ИСПРАВЛЕНО★: вместо русско-специфичных regex используем:
    1. Длину токенов (> 8 слов → complex)
    2. Многофасетные вопросы (multiple question words)
    3. Наличие query-слов (and, also, how, why, compare, difference, etc.)
    """
    query_lower = query.lower()

    # 1. Короткий запрос (≤ 5 слов) — всегда simple
    token_count = len(query.split())
    if token_count <= 5:
        return False

    # 2. Длинный запрос (> 15 слов) — всегда complex
    if token_count > 15:
        return True

    # 3. Multi-question words: "how and why", "find and compare", etc.
    complex_words = {
        "и",
        "а",
        "также",
        "плюс",  # Russian
        "and",
        "also",
        "plus",
        "both",  # English conjunctives
        "how",
        "why",
        "compare",  # Question/analysis words
        "difference",
        "between",
        "explain",  # Deep analysis indicators
        "related",
        "depends",
        "impact",  # Graph-needed words
    }
    word_count = sum(1 for w in complex_words if w in query_lower)

    # 4. Наличие запятых (перечисление) + длина
    comma_count = query.count(",")
    has_multiple_entities = comma_count >= 2

    # 5. Фразы-инструкции (анализ связей)
    phrase_indicators = [
        "как работает",
        "почему падает",
        "проанализируй связь",
        "how does",
        "why does",
        "analyze the relationship",
        "find all",
        "what is the difference",
    ]
    has_phrase = any(p in query_lower for p in phrase_indicators)

    return word_count >= 2 or has_multiple_entities or has_phrase or token_count > 50


# ══════════════════════════════════════════════════════════
# Search Tools
# ══════════════════════════════════════════════════════════


class SearchCodeTool(MCPTool):
    """search_code — семантический поиск по коду (vector + BM25 + agentic)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="search_code")

    @error_boundary("search_code", timeout_ms=15000, max_retries=1)
    async def execute(
        self,
        query: str,
        mode: str = "auto",
        limit: int = 6,
        filter_layer: Optional[str] = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        await self.require_ready_project()

        if not query or not query.strip():
            return "❌ Query is empty"

        # === Project header (INC-6BCB-v3) ===
        # Показываем где ищем — чтобы пользователь видел ГДЕ идёт поиск.
        # Особенно важно при multi-window: может искать в чужом проекте.
        project_header = self._project_header()
        # Добавляем информацию о фильтре слоя
        if filter_layer:
            project_header += f"\n🔬 Layer filter: {filter_layer}"

        # === Диспетчеризация по режиму ===
        if mode in ("fast", "quality", "smart"):
            raw = self.resolve_searcher().search_with_mode(
                query, mode=mode, limit=limit, layer=filter_layer
            )
            # search_with_mode может вернуть строку (ошибка embedder)
            if isinstance(raw, str):
                return project_header + "\n" + raw
            return self._format_results(raw, mode, project_header=project_header)

        if mode == "deep":
            return (
                project_header
                + "\n"
                + self.resolve_searcher().deep_search(query, limit=limit)
            )

        if mode == "context":
            return (
                project_header
                + "\n"
                + self.resolve_searcher().context_search(query, limit=limit)
            )

        # === mode == "auto": авто-определение simple vs agentic ===
        since = kwargs.get("since") if kwargs else None
        before = kwargs.get("before") if kwargs else None

        if _is_complex_query(query):
            return project_header + "\n" + await self._agentic_search(query)
        return (
            project_header
            + "\n"
            + self.resolve_searcher().search(
                query,
                limit=limit,
                since=since,
                before=before,
                layer=filter_layer,
            )
        )

    async def _agentic_search(self, query: str) -> str:
        """Agentic Code Search с декомпозицией и связями.

        Multi-window (INC-6BCB-v2): self.searcher / self.symbol_index
        НЕ существуют в базовом MCPTool (Indexer per-project → Searcher
        per-project). Резолвим через resolve_searcher() / resolve_symbol_index().
        """
        searcher = self.resolve_searcher()
        symbol_index = self.resolve_symbol_index()
        try:
            results, metadata = searcher.agentic_code_search(
                query,
                symbol_index=symbol_index,
                max_subqueries=4,
                limit_per_subquery=5,
                max_total_results=10,
            )
            return searcher._format_agentic_results(results, metadata)
        except Exception as e:
            logger.error(f"Agentic search failed, fallback to simple: {e}")
            return searcher.search(query, limit=6)

    @staticmethod
    def _format_results(result: Any, mode: str, project_header: str = "") -> str:
        """Форматирует результаты поиска через единый UI-форматтер."""
        # Если search вернул ошибку (строка) — возвращаем как есть
        if isinstance(result, str):
            return (project_header + "\n" + result) if project_header else result

        # Если не dict — ничего не делаем
        if not isinstance(result, dict):
            return project_header

        results = result.get("results", [])
        timing = result.get("timing_ms", {})
        exec_ms = int(timing.get("total_ms", 0))

        query = result.get("query", f"mode={mode}")

        # Конвертируем внутрений формат результатов в формат ui_formatter
        ui_items = []
        for r in results:
            meta = r.get("metadata", {})
            ui_items.append(
                {
                    "file_path": meta.get("file", r.get("file_path", "")),
                    "start_line": meta.get("start_line", meta.get("chunk_index", "")),
                    "text": r.get("text_full", r.get("text", "")),
                    "layer": meta.get("layer", ""),
                    "score": r.get("final_score", r.get("score", 0)),
                }
            )

        output = project_header + "\n" if project_header else ""
        output += format_search_code(query, ui_items, exec_ms, mode)
        return output


class GetSymbolInfoTool(MCPTool):
    """get_symbol_info — граф вызовов для символа."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_symbol_info")

    @error_boundary("get_symbol_info", timeout_ms=5000)
    async def execute(
        self,
        query: str,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        await self.require_ready_project()
        call_graph = self.resolve_symbol_index().build_call_graph(query, depth=2)

        if call_graph["definition"] or call_graph["callers"] or call_graph["callees"]:
            defs = call_graph["definition"]
            callers = call_graph["callers"][:15]
            callees = call_graph["callees"][:10]
            result = f"🔍 **{query}** — {len(defs)} определение, {len(callers)} caller'ов, {len(callees)} callee\n\n"
            if defs:
                d = defs[0]
                result += f"📄 Определение: `{d.get('file', '?')}` строка {d.get('line', '?')}\n"
            if callers:
                result += f"\n⬆️ **Вызывается из:**\n"
                for c in callers[:5]:
                    result += f"   • `{c.get('symbol', '?')}` → {c.get('file', '?')}:{c.get('line', '?')}\n"
            if callees:
                result += f"\n⬇️ **Вызывает:**\n"
                for c in callees[:5]:
                    result += f"   • `{c.get('symbol', '?')}` → {c.get('file', '?')}:{c.get('line', '?')}\n"
            return result

        # Fallback: поиск по имени
        results = self.resolve_symbol_index().search_symbols(query)
        if not results:
            return f"ℹ️ **{query}** — не найден\n"

        defs = [r for r in results if getattr(r, "is_definition", False)]
        usages = [r for r in results if not getattr(r, "is_definition", False)]
        result = (
            f"🔍 **{query}** — {len(defs)} определений, {len(usages)} использований\n\n"
        )
        if defs:
            result += "📄 **Определения:**\n"
            for d in defs[:5]:
                result += f"   • `{d.file_path}` строка {d.line} ({d.kind})\n"
        if usages:
            result += f"\n📎 **Использования:**\n"
            for u in usages[:5]:
                result += f"   • `{u.file_path}` строка {u.line}\n"
        return result


class ImpactAnalysisTool(MCPTool):
    """impact_analysis — анализ влияния изменения символа."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="impact_analysis")

    @error_boundary("impact_analysis", timeout_ms=20000)
    async def execute(
        self,
        symbol: str,
        depth: int = 3,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        await self.require_ready_project()
        result = self.resolve_symbol_index().get_impact_analysis(symbol, depth=depth)

        if not result.get("call_graph", {}).get("definition"):
            return {
                "status": "warning",
                "message": f"Symbol '{symbol}' not found in index",
            }

        return {
            "status": "ok",
            "symbol": symbol,
            "depth": depth,
            "direct_callers": result["direct_callers"],
            "transitive_callers": result["transitive_callers"],
            "direct_callees": result["direct_callees"],
            "transitive_callees": result["transitive_callees"],
            "risk_level": result["risk_level"],
            "risk_score": result["risk_score"],
            "affected_files": result["affected_files"],
            "affected_modules": result.get("affected_modules", []),
        }


__all__ = [
    "SearchCodeTool",
    "GetSymbolInfoTool",
    "ImpactAnalysisTool",
    "_is_complex_query",
]
