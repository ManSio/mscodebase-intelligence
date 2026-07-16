"""Поисковые инструменты: search_code, get_symbol_info, impact_analysis.

ИСПРАВЛЕНО (v2):
- _auto_search: заменена русская грамматическая эвристика на токен-базированную
- Добавлена поддержка английских индикаторов сложности
- search_code возвращает JSON с полями status + results
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from src.config.settings import get_config
from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool
from src.utils.i18n import _
from src.utils.ui_formatter import format_search_code

logger = logging.getLogger("mscodebase_server.search_tools")


# ══════════════════════════════════════════════════════════
# Adaptive search budget (CodeGraph-inspired)
# Размер ответа подстраивается под размер проекта.
# ══════════════════════════════════════════════════════════


def _get_search_budget(searcher) -> int:
    """Возвращает оптимальный limit для search_code под размер проекта.

    Маленькие проекты (<500 файлов): меньше результатов (быстрее, дешевле).
    Большие проекты (>15000 файлов): больше результатов (чтобы не потерять).
    """
    try:
        indexer = getattr(searcher, 'indexer', None)
        if indexer is None:
            return 6
        cache = getattr(indexer, '_cached_unique_files', None)
        if isinstance(cache, set):
            count = len(cache)
        elif isinstance(cache, int):
            count = cache
        else:
            status = indexer.get_status() if hasattr(indexer, 'get_status') else {}
            count = status.get('unique_files', 0) if isinstance(status, dict) else 0
            count = count or 0

        # CodeGraph-inspired budget:
        if count == 0:
            return 6
        elif count < 500:
            return 4
        elif count < 5000:
            return 6
        elif count < 15000:
            return 8
        else:
            return 10
    except Exception:
        return 6


# ══════════════════════════════════════════════════════════
# Staleness checker (CodeGraph-inspired)
# Предупреждает, если индекс мог устареть после индексации.
# ══════════════════════════════════════════════════════════

# Время старта MCP-сервера (для сравнения с indexed_at)
_MCP_START_TIME = time.time()


def _get_stale_warning(searcher) -> str:
    """Проверяет, актуален ли индекс, и возвращает предупреждение если нет.

    Стратегия (без полного сканирования файлов):
    1. Берём самый свежий indexed_at из LanceDB
    2. Если MCP запущен ПОСЛЕ последней индексации — файлы могли измениться
    3. Показываем баннер один раз ("may be stale")
    """
    try:
        indexer = getattr(searcher, 'indexer', None)
        if indexer is None or not hasattr(indexer, 'table') or indexer.table is None:
            return ''
        # Быстрый запрос: max(indexed_at) через SQL
        table = indexer.table
        result = table.search().select(["indexed_at"]).limit(1).to_pandas()
        if result.empty:
            return ''
        latest = str(result["indexed_at"].iloc[0])
        if not latest:
            return ''
        try:
            latest_dt = datetime.fromisoformat(latest)
            latest_ts = latest_dt.timestamp()
        except Exception:
            return ''

        if _MCP_START_TIME > latest_ts + 10:  # 10s запас на погрешность
            return ''  # молчим, если старт был после последней индексации (всё свежее)

        elapsed = time.time() - latest_ts
        if elapsed > 3600:  # >1 часа
            return '⚠️ Index may be stale (last indexed >1h ago). Run intel_trigger_reindex or wait for next auto-sync.\n'
        elif elapsed > 600:  # >10 мин
            return '⚠️ Index may be stale (last indexed >10min ago). Consider re-indexing if files changed.\n'
        return ''
    except Exception:
        return ''


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
        intent_hint: str = "auto",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        from src.core.error_handler import record_tool_result

        await self.require_ready_project()

        if not query or not query.strip():
            return _("❌ Query is empty")

        # P1: Adaptive search budget (CodeGraph-inspired)
        # Адаптируем limit под размер проекта если не указан явно.
        searcher = self.resolve_searcher()
        adaptive_limit = _get_search_budget(searcher)
        effective_limit = limit if limit != 6 else adaptive_limit

        # P3: Staleness check
        stale_banner = _get_stale_warning(searcher)

        # === Project header ===
        project_header = self._project_header()
        if filter_layer:
            project_header += _("\n🔬 Layer filter: {layer}", layer=filter_layer)
        if effective_limit != limit:
            project_header += _("\n📊 Adaptive limit: {n} results for this project size", n=effective_limit)

        result_str: str
        results_count: int = 0
        raw = None  # для телеметрии

        # === Диспетчеризация по режиму ===
        if mode in ("fast", "quality", "smart"):
            raw = self.resolve_searcher().search_with_mode(
                query,
                mode=mode,
                limit=effective_limit,
                layer=filter_layer,
                intent_hint=intent_hint,
            )
            if isinstance(raw, str):
                result_str = stale_banner + project_header + "\n" + raw
            else:
                results_count = len(raw.get("results", []))
                result_str = stale_banner + self._format_results(
                    raw, mode, project_header=project_header
                )

        elif mode == "deep":
            raw = None  # deep_search возвращает str
            result_str = (
                stale_banner
                + project_header
                + "\n"
                + self.resolve_searcher().deep_search(query, limit=effective_limit)
            )

        elif mode == "context":
            raw = None  # context_search возвращает str
            result_str = (
                stale_banner
                + project_header
                + "\n"
                + self.resolve_searcher().context_search(query, limit=effective_limit)
            )

        elif mode == "ask":
            # mode=ask: генерация ответа через phi-4
            # В light profile — fallback на quality (защита от CPU-фриза)
            perf_config = get_config().performance
            if perf_config.is_light_profile:
                logger.info(
                    "mode=ask заблокирован в light profile. "
                    "Переключение на mode=quality."
                )
                raw = self.resolve_searcher().search_with_mode(
                    query,
                    mode="quality",
                    limit=effective_limit,
                    layer=filter_layer,
                    intent_hint=intent_hint,
                )
                if isinstance(raw, str):
                    result_str = stale_banner + project_header + "\n" + raw
                else:
                    results_count = len(raw.get("results", []))
                    result_str = stale_banner + self._format_results(
                        raw, mode, project_header=project_header
                    )
            else:
                raw = None  # ask_async возвращает str
                result_str = (
                    stale_banner
                    + project_header
                    + "\n"
                    + await self.resolve_searcher().ask_async(query, limit=effective_limit)
                )

        else:
            # auto
            raw = None  # auto возвращает str
            since = kwargs.get("since") if kwargs else None
            before = kwargs.get("before") if kwargs else None
            if _is_complex_query(query):
                result_str = stale_banner + project_header + "\n" + await self._agentic_search(query)
            else:
                result_str = (
                    stale_banner
                    + project_header
                    + "\n"
                    + self.resolve_searcher().search(
                        query,
                        limit=effective_limit,
                        since=since,
                        before=before,
                        layer=filter_layer,
                    )
                )

        # Обогащаем телеметрию
        confidence = 0.85 if results_count > 0 else 0.3
        detail = f"{results_count} results, mode={mode}"
        if filter_layer:
            detail += f", layer={filter_layer}"
        if intent_hint and intent_hint != "auto":
            detail += f", intent={intent_hint}"
        # Добавляем модель из результата поиска
        if isinstance(raw, dict):
            mi = raw.get("model_info")
            if mi:
                detail += f", models={mi}"
                if raw.get("cache_hit"):
                    detail += " (cached)"
            # Per-stage timing
            rt = raw.get("rerank_timing", {})
            if rt:
                s1 = rt.get("stage1_ms", 0)
                s2 = rt.get("stage2_ms", 0)
                if s1 or s2:
                    detail += f", stages: emb={int(s1)}ms llm={int(s2)}ms tot={int(rt.get('total_ms', 0))}ms"
        record_tool_result(
            "search_code",
            route=mode,
            confidence=confidence,
            results_count=results_count,
            detail=detail,
        )

        return result_str

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
            item = {
                "file_path": meta.get("file", r.get("file_path", "")),
                "start_line": meta.get("start_line", meta.get("chunk_index", "")),
                "text": r.get("text_full", r.get("text", "")),
                "layer": meta.get("layer", ""),
                "score": r.get("final_score", r.get("score", 0)),
            }
            # Graph context enrich (callers from SymbolIndex)
            callers = meta.get("callers")
            if callers:
                item["callers"] = callers
            callee_count = meta.get("callee_count")
            if callee_count:
                item["callee_count"] = callee_count
            ui_items.append(item)

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
            result = _(
                "🔍 **{query}** — {defs} defs, {callers} callers, {callees} callees\n\n",
                query=query,
                defs=len(defs),
                callers=len(callers),
                callees=len(callees),
            )
            if defs:
                d = defs[0]
                result += _(
                    "📄 Definition: `{file}` line {line}\n",
                    file=d.get("file", "?"),
                    line=d.get("line", "?"),
                )
            if callers:
                result += _("\n⬆️ **Called from:**\n")
                for c in callers[:5]:
                    result += f"   • `{c.get('symbol', '?')}` → {c.get('file', '?')}:{c.get('line', '?')}\n"
            if callees:
                result += _("\n⬇️ **Calls:**\n")
                for c in callees[:5]:
                    result += f"   • `{c.get('symbol', '?')}` → {c.get('file', '?')}:{c.get('line', '?')}\n"
            return result

        # Fallback: поиск по имени
        results = self.resolve_symbol_index().search_symbols(query)
        if not results:
            return _("ℹ️ **{query}** — not found\n", query=query)

        defs = [r for r in results if getattr(r, "is_definition", False)]
        usages = [r for r in results if not getattr(r, "is_definition", False)]
        result = _(
            "🔍 **{query}** — {defs} definitions, {usages} usages\n\n",
            query=query,
            defs=len(defs),
            usages=len(usages),
        )
        if defs:
            result += _("📄 **Definitions:**\n")
            for d in defs[:5]:
                result += f"   • `{d.file_path}` строка {d.line} ({d.kind})\n"
        if usages:
            result += _("\n📎 **Usages:**\n")
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
        from src.core.error_handler import record_tool_result

        await self.require_ready_project()
        # CPU-bound: get_impact_analysis делает BFS по графу — выгружаем в ThreadPool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self.resolve_symbol_index().get_impact_analysis,
            symbol,
            depth,
        )

        if not result.get("call_graph", {}).get("definition"):
            record_tool_result(
                "impact_analysis", route="graph", confidence=0.0, results_count=0
            )
            return {
                "status": "warning",
                "message": _("Symbol '{symbol}' not found in index", symbol=symbol),
            }

        # Guard: защита от не-списковых значений (B2 — TypeError в логах)
        def _safe_count(v):
            return (
                    len(v) if isinstance(v, (list, str, dict)) else int(v or 0)
                )
        dc = _safe_count(result.get("direct_callers", 0))
        tc = _safe_count(result.get("transitive_callers", 0))
        dcal = _safe_count(result.get("direct_callees", 0))
        tcal = _safe_count(result.get("transitive_callees", 0))
        total = dc + tc + dcal + tcal
        record_tool_result(
            "impact_analysis",
            route="graph",
            confidence=0.85 if total > 0 else 0.3,
            results_count=total,
            detail=f"{dc} callers, {dcal} callees",
        )

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
