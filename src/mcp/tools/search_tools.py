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

    @error_boundary("search_code", timeout_ms=15000, max_retries=1)
    async def execute(
        self,
        query: str,
        mode: str = "auto",
        limit: int = 6,
        filter_layer: Optional[str] = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        self.require_index()

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
            return self._format_results(
                self.resolve_searcher().search_with_mode(
                    query, mode=mode, limit=limit, layer=filter_layer
                ),
                mode,
                project_header=project_header,
            )

        if mode == "deep":
            return project_header + "\n" + self.resolve_searcher().deep_search(query, limit=limit)

        if mode == "context":
            return project_header + "\n" + self.resolve_searcher().context_search(query, limit=limit)

        # === mode == "auto": авто-определение simple vs agentic ===
        since = kwargs.get("since") if kwargs else None
        before = kwargs.get("before") if kwargs else None

        if _is_complex_query(query):
            return project_header + "\n" + await self._agentic_search(query)
        return project_header + "\n" + self.resolve_searcher().search(
            query, limit=limit, since=since, before=before, layer=filter_layer,
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
    def _format_results(result: dict, mode: str, project_header: str = "") -> str:
        """Форматирует результаты smart search в читаемый текст.

        INC-6BCB-v3: project_header добавляется в начало output,
        чтобы пользователь видел ГДЕ именно идёт поиск.
        """
        results = result.get("results", [])
        timing = result.get("timing_ms", {})

        mode_emoji = {"fast": "⚡", "quality": "🎯", "smart": "🎯"}
        lines = []
        if project_header:
            lines.append(project_header)
        lines.append(f"{mode_emoji.get(mode, '🔍')} Search [{mode.upper()}]")

        if not results:
            lines.append("  🔍 По запросу ничего не найдено.")
            return "\n".join(lines)

        lines.append(f"  Results: {len(results)}")
        lines.append(f"  Time: {timing.get('total_ms', 0):.0f}ms")
        if result.get("cache_hit"):
            lines.append("  Cache: HIT ✅")
        lines.append("")

        for i, res in enumerate(results, 1):
            score = res.get("final_score", res.get("score", 0))
            file_path = res["metadata"]["file"]
            chunk_idx = res["metadata"]["chunk_index"]
            code = res.get("text_full", res.get("text", ""))[:200]

            lines.append(f"{i}. 📄 {file_path} [Chunk #{chunk_idx}] (score: {score:.3f})")
            if code:
                lines.append(f"```\n{code}\n```")
            lines.append("-" * 40)

        return "\n".join(lines)


class GetSymbolInfoTool(MCPTool):
    """get_symbol_info — граф вызовов для символа."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_symbol_info")

    @error_boundary("get_symbol_info", timeout_ms=5000)
    async def execute(
        self,
        query: str,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        call_graph = self.resolve_symbol_index().build_call_graph(query, depth=2)

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
        results = self.resolve_symbol_index().search_symbols(query)
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

    @error_boundary("impact_analysis", timeout_ms=20000)
    async def execute(
        self,
        symbol: str,
        depth: int = 3,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
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
