"""get_context — task-shaped инструмент: контекст по нескольким целям одним вызовом.

Вместо N вызовов get_symbol_info/impact_analysis агент передаёт список целей
и получает агрегированный контекст (31.6% token reduction по benchmark repowise;
у нас — обёртка над существующими тулами, без нового анализа).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool
from src.mcp.tools.search_tools import GetSymbolInfoTool, ImpactAnalysisTool

_MAX_TARGETS = 10


class GetContextTool(MCPTool):
    """get_context — агрегированный контекст для нескольких символов."""

    def __init__(self, services):
        super().__init__(services, tool_name="get_context")

    @error_boundary("get_context", timeout_ms=30000)
    async def execute(
        self,
        targets: Optional[List[str]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        _kwargs = kwargs or {}
        targets = targets if targets is not None else _kwargs.get("targets", [])
        if isinstance(targets, str):
            targets = [t.strip() for t in targets.split(",") if t.strip()]
        targets = [t for t in targets if t][:_MAX_TARGETS]

        if not targets:
            return {
                "status": "error",
                "message": (
                    "targets обязателен: get_context(targets=['Indexer', 'Searcher'])"
                ),
            }

        symbol_tool = GetSymbolInfoTool(self._services)
        impact_tool = ImpactAnalysisTool(self._services)

        context: Dict[str, Any] = {}
        for target in targets:
            item: Dict[str, Any] = {}
            try:
                item["symbol_info"] = await symbol_tool.execute(target)
            except Exception as e:  # noqa: BLE001 — агрегируем, не роняем весь вызов
                item["symbol_info"] = {"status": "error", "message": str(e)}
            try:
                item["impact"] = await impact_tool.execute(target)
            except Exception as e:  # noqa: BLE001
                item["impact"] = {"status": "error", "message": str(e)}
            context[target] = item

        return {
            "status": "ok",
            "targets": targets,
            "total_targets": len(targets),
            "context": context,
        }
