# -*- coding: utf-8 -*-
"""Bootstrap Pipeline tool: dynamic trace + TESTS-рёбра одной командой.

Единая точка запуска Step 3 из MCP: ``bootstrap_pipeline(project_root, ...)``.

Дизайн (Тумблер: core-интерфейс, provider-детали):
- Вся логика в src/core/bootstrap_pipeline.run_bootstrap_pipeline() —
  sync, детерминированный, JSON-сериализуемый BootstrapPipelineStats.
- Тул только: (1) резолвит project_root (явный → active project из registry),
  (2) делегирует в asyncio.to_thread (pytest-субпроцесс НЕ блокирует
  event loop JSON-RPC), (3) возвращает as_dict()-отчёт.

Не назначает timeout_ms на error_boundary: лимит реального прогона задаётся
trace_timeout (default 600s из MSCODEBASE_BOOTSTRAP_TRACE_TIMEOUT) — это
in-product предел, не транспортный.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.error_handler import ToolError, error_boundary
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.bootstrap_tool")


class BootstrapPipelineTool(MCPTool):
    """bootstrap_pipeline — шаг 3: сущности + dynamic trace + TESTS-рёбра в граф."""

    tool_name = "bootstrap_pipeline"

    def __init__(self, services):
        super().__init__(services, tool_name=self.tool_name)

    @error_boundary("bootstrap_pipeline")
    async def execute(
        self,
        project_root: str = "",
        src_dir: str = "",
        graph_path: str = "",
        extra_pytest_args: Optional[List[str]] = None,
        trace_timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Dict:
        # multi-window: явный проект приоритетнее, иначе active project из registry.
        root = self._resolve_project_root(project_root)
        if root is None:
            raise ToolError(
                status="error",
                message="bootstrap_pipeline: project_root не определён",
                detail=(
                    "Передайте project_root явно, либо откройте проект в Zed "
                    "(LSP запишет его в bridge)."
                ),
            )

        src = Path(src_dir).resolve() if src_dir else None
        graph = Path(graph_path).resolve() if graph_path else None

        from src.core.bootstrap_pipeline import run_bootstrap_pipeline

        result = await asyncio.to_thread(
            run_bootstrap_pipeline,
            root,
            src_dir=src,
            graph_path=graph,
            extra_pytest_args=extra_pytest_args,
            trace_timeout=trace_timeout,
        )

        report = result.as_dict()
        report["summary"] = (
            f"src={report.get('src_root')}, "
            f"entities={report['entities'].get('entities_found')}, "
            f"tests={report['trace'].get('tests_total')} "
            f"({report['trace'].get('linked_pct')}% linked), "
            f"TESTS-edges={report['graph'].get('edges_added')}"
        )
        return report

    def _resolve_project_root(self, explicit: str) -> Optional[Path]:
        if explicit and explicit.strip():
            p = Path(explicit).resolve()
            return p if p.is_dir() else None
        try:
            idx = self.resolve_indexer()
            p = getattr(idx, "project_path", None)
            return Path(p).resolve() if p else None
        except Exception:  # noqa: BLE001 — fallback: не смогли резолвить → None
            return None


__all__ = ["BootstrapPipelineTool"]
