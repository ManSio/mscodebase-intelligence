"""Инструменты расследований: get_bug_correlation, get_hotspots, find_similar_bugs.

Все инструменты получают зависимости через DI и используют error_boundary.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.core.indexer import Indexer
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.investigation_tools")


class GetBugCorrelationTool(MCPTool):
    """get_bug_correlation — анализ связи багов с изменениями в коде."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_bug_correlation")

    @error_boundary("get_bug_correlation", timeout_ms=20000)
    async def execute(
        self,
        project_root: str = "",
        file_path: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.bug_correlation import BugCorrelation
        from src.core.commit_memory import CommitMemory

        target_path = (
            Path(project_root).resolve()
            if project_root
            else self.resolve_indexer().project_path
        )
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {target_path}"}

        memory = CommitMemory(target_path)
        bug_corr = BugCorrelation(memory)

        if file_path:
            history = bug_corr.get_bug_history_for_file(file_path)
            return {
                "status": "ok",
                "mode": "file",
                "file": file_path,
                "bug_risk": history.get("bug_risk", "low"),
                "bug_count": history.get("bug_count", 0),
                "total_commits": history.get("total_commits", 0),
                "bug_ratio": round(history.get("bug_ratio", 0), 3),
                "bug_commits": [
                    {
                        "hash": c["hash"][:8],
                        "date": c.get("date", "")[:10],
                        "message": c.get("message", "")[:60],
                    }
                    for c in history.get("bug_commits", [])[:5]
                ],
            }

        stats = bug_corr.analyze()
        hotspots = bug_corr.get_hotspots(10)

        return {
            "status": "ok",
            "mode": "project",
            "total_commits": stats.get("total_commits", 0),
            "bugfix_commits": stats.get("bugfix_commits", 0),
            "bugfix_ratio": round(stats.get("bugfix_ratio", 0), 3),
            "hotspots": [
                {
                    "file": h["file"],
                    "bug_count": h.get("bug_count", 0),
                    "risk": h.get("risk", "unknown"),
                    "score": round(h.get("bug_score", 0), 2),
                }
                for h in hotspots
            ],
        }


class GetHotspotsTool(MCPTool):
    """get_hotspots — горячие точки с высоким баго-рейтом."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_hotspots")

    @error_boundary("get_hotspots", timeout_ms=15000)
    async def execute(
        self, project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        from src.core.commit_memory import CommitMemory

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {project_root}"}

        memory = CommitMemory(target_path)
        hotspots = memory.get_hotspots(min_changes=3)

        if not hotspots:
            return {"status": "ok", "hotspots": []}

        return {
            "status": "ok",
            "project": target_path.name,
            "hotspots": [
                {
                    "file": h["file"],
                    "total_changes": h.get("total_changes", 0),
                    "bugfix_changes": h.get("bugfix_changes", 0),
                    "bug_ratio": round(h.get("bug_ratio", 0), 3),
                    "risk": h.get("risk", "low"),
                }
                for h in hotspots[:10]
            ],
        }


class FindSimilarBugsTool(MCPTool):
    """find_similar_bugs — поиск похожих багов из истории."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="find_similar_bugs")

    @error_boundary("find_similar_bugs", timeout_ms=15000)
    async def execute(
        self,
        error_message: str,
        project_root: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.commit_memory import CommitMemory

        target_path = (
            Path(project_root).resolve()
            if project_root
            else self.resolve_indexer().project_path
        )
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {target_path}"}

        memory = CommitMemory(target_path)
        similar = memory.find_similar_bugs(error_message, max_results=5)

        if not similar:
            return {
                "status": "ok",
                "query": error_message[:50],
                "matches": 0,
                "similar_bugs": [],
            }

        return {
            "status": "ok",
            "query": error_message[:60],
            "matches": len(similar),
            "similar_bugs": [
                {
                    "hash": bug["hash"],
                    "date": bug.get("date", "")[:10],
                    "message": bug.get("message", "")[:80],
                    "relevance": round(bug.get("relevance_score", 0), 2),
                    "files": bug.get("files", [])[:3],
                }
                for bug in similar
            ],
        }


__all__ = [
    "GetBugCorrelationTool",
    "GetHotspotsTool",
    "FindSimilarBugsTool",
]
