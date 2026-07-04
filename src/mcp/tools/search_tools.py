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
from src.core.error_handler import error_boundary, IndexNotReadyError
from src.core.indexer import Indexer
from src.core.searcher import Searcher
from src.core.symbol_index import SymbolIndex
from src.mcp.tools.base import MCPTool

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
        "и", "а", "также", "плюс",        # Russian
        "and", "also", "plus", "both",     # English conjunctives
        "how", "why", "compare",           # Question/analysis words
        "difference", "between", "explain", # Deep analysis indicators
        "related", "depends", "impact",    # Graph-needed words
    }
    word_count = sum(1 for w in complex_words if w in query_lower)

    # 4. Наличие запятых (перечисление) + длина
    comma_count = query.count(",")
    has_multiple_entities = comma_count >= 2

    # 5. Фразы-инструкции (анализ связей)
    phrase_indicators = [
        "как работает", "почему падает", "проанализируй связь",
        "how does", "why does", "analyze the relationship",
        "find all", "what is the difference",
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
        self.searcher = services.resolve(Searcher)
        self.symbol_index = services.resolve(SymbolIndex)

    @error_boundary("search_code", timeout_ms=15000, max_retries=1)
    async def execute(
        self,
        query: str,
        mode: str = "auto",
        limit: int = 6,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        self.require_index()

        if not query or not query.strip():
            return {"status": "error", "message": "Query is empty"}

        # === Диспетчеризация по режиму ===
        if mode in ("fast", "quality", "smart"):
            result = self.searcher.search_with_mode(query, mode=mode, limit=limit)
            return self._format_results(result, mode)

        if mode == "deep":
            return self.searcher.deep_search(query, limit=limit)

        if mode == "context":
            return self.searcher.context_search(query, limit=limit)

        # === mode == "auto": авто-определение simple vs agentic ===
        since = kwargs.get("since") if kwargs else None
        before = kwargs.get("before") if kwargs else None

        if _is_complex_query(query):
            return await self._agentic_search(query)
        return self.searcher.search(query, limit=limit, since=since, before=before)

    async def _agentic_search(self, query: str) -> str:
        """Agentic Code Search с декомпозицией и связями."""
        try:
            results, metadata = self.searcher.agentic_code_search(
                query,
                symbol_index=self.symbol_index,
                max_subqueries=4,
                limit_per_subquery=5,
                max_total_results=10,
            )
            return self.searcher._format_agentic_results(results, metadata)
        except Exception as e:
            logger.error(f"Agentic search failed, fallback to simple: {e}")
            return self.searcher.search(query, limit=6)

    @staticmethod
    def _format_results(result: dict, mode: str) -> dict:
        """Форматирует результаты smart search."""
        results = result.get("results", [])
        timing = result.get("timing_ms", {})

        formatted = []
        for res in results:
            score = res.get("final_score", res.get("score", 0))
            formatted.append({
                "file": res["metadata"]["file"],
                "chunk_index": res["metadata"]["chunk_index"],
                "score": round(score, 4),
                "text": res.get("text_full", res.get("text", ""))[:300],
            })

        return {
            "status": "ok",
            "mode": mode,
            "results_count": len(formatted),
            "total_ms": timing.get("total_ms", 0),
            "results": formatted,
        }


class GetSymbolInfoTool(MCPTool):
    """get_symbol_info — граф вызовов для символа."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_symbol_info")
        self.symbol_index = services.resolve(SymbolIndex)

    @error_boundary("get_symbol_info", timeout_ms=5000)
    async def execute(
        self,
        query: str,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        call_graph = self.symbol_index.build_call_graph(query, depth=2)

        if call_graph["definition"] or call_graph["callers"] or call_graph["callees"]:
            return {
                "status": "ok",
                "symbol": query,
                "definition": call_graph["definition"],
                "callers": call_graph["callers"][:15],
                "callees": call_graph["callees"][:10],
                "impact_files": call_graph["impact_files"][:10],
            }

        # Fallback: поиск по имени
        results = self.symbol_index.search_symbols(query)
        if not results:
            return {
                "status": "warning",
                "message": f"Symbol '{query}' not found",
            }

        definitions = [r for r in results if getattr(r, "is_definition", False)]
        usages = [r for r in results if not getattr(r, "is_definition", False)]

        return {
            "status": "ok",
            "symbol": query,
            "definitions": [
                {"file": d.file_path, "line": d.line, "kind": d.kind}
                for d in definitions
            ],
            "usages": [
                {"file": u.file_path, "line": u.line}
                for u in usages[:10]
            ],
        }


class ImpactAnalysisTool(MCPTool):
    """impact_analysis — анализ влияния изменения символа."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="impact_analysis")
        self.symbol_index = services.resolve(SymbolIndex)

    @error_boundary("impact_analysis", timeout_ms=20000)
    async def execute(
        self,
        symbol: str,
        depth: int = 3,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        result = self.symbol_index.get_impact_analysis(symbol, depth=depth)

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
