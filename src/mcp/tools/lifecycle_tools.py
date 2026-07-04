"""Инструменты жизненного цикла: submit_background_task, get_task_status, verify_action.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.core.indexer import Indexer
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.lifecycle_tools")


class SubmitBackgroundTaskTool(MCPTool):
    """submit_background_task — запуск долгой задачи в фоне."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="submit_background_task")

    @error_boundary("submit_background_task", timeout_ms=5000)
    async def execute(
        self, task_type: str, project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        from src.core.bug_correlation import BugCorrelation
        from src.core.commit_memory import CommitMemory
        from src.core.relation_extractor import RelationExtractor
        from src.core.eta_predictor import get_predictor
        from src.core.task_queue import get_task_queue

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {project_root}"}

        task_queue = get_task_queue()
        memory = CommitMemory(target_path)
        predictor = get_predictor()

        if task_type == "bug_correlation":
            task_id = task_queue.submit_sync(
                "Bug Correlation Analysis",
                lambda: self._run_bug_correlation(memory),
                memory,
            )
        elif task_type == "build_knowledge_graph":
            task_id = task_queue.submit_sync(
                "Build Knowledge Graph",
                lambda: self._run_build_graph(memory),
                memory,
            )
        elif task_type == "full_analysis":
            task_id = task_queue.submit_sync(
                "Full Analysis",
                lambda: self._run_full_analysis(memory),
                memory,
            )
        else:
            return {"status": "error", "message": f"Unknown task type: {task_type}"}

        eta = predictor.estimate(task_type)
        return {
            "status": "ok",
            "task_id": task_id,
            "task_type": task_type,
            "eta_seconds": eta.get("estimated_seconds", 60),
        }

    def _run_bug_correlation(self, memory) -> str:
        from src.core.bug_correlation import BugCorrelation

        bug_corr = BugCorrelation(memory)
        stats = bug_corr.analyze()
        hotspots = bug_corr.get_hotspots(10)

        lines = [
            f"Bug Correlation Analysis",
            f"Total commits: {stats['total_commits']}",
            f"Bugfixes: {stats['bugfix_commits']} ({stats['bugfix_ratio']:.1%})",
            f"Hotspots: {len(hotspots)}",
        ]
        return "\n".join(lines)

    def _run_build_graph(self, memory) -> str:
        from src.core.relation_extractor import RelationExtractor

        extractor = RelationExtractor(memory)
        relations = extractor.extract_all_relations()
        summary = extractor.get_relation_summary()

        return f"Knowledge Graph: {summary.get('total_relations', 0)} relations"

    def _run_full_analysis(self, memory) -> str:
        return f"{self._run_bug_correlation(memory)}\n\n{self._run_build_graph(memory)}"


class GetTaskStatusTool(MCPTool):
    """get_task_status — статус фоновой задачи."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_task_status")

    @error_boundary("get_task_status", timeout_ms=3000)
    async def execute(
        self, task_id: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> str:
        from src.core.task_queue import get_task_queue

        task_queue = get_task_queue()
        status = task_queue.get_status(task_id)

        if not status:
            return f"❌ Task not found: {task_id}"

        lines = [f"📋 Task: {status['name']}"]
        lines.append(f"  ID: {status['id']}")
        lines.append(f"  Status: {status['status']}")
        lines.append(f"  Progress: {status.get('progress', 0) * 100:.0f}%")

        if status.get("error"):
            lines.append(f"  Error: {status['error']}")
        if status.get("result"):
            result = status['result']
            if isinstance(result, str):
                lines.append(f"  Result: {result[:200]}")

        return "\n".join(lines)


class VerifyActionTool(MCPTool):
    """verify_action — верификация выполненного действия (Execution Contract)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="verify_action")

    @error_boundary("verify_action", timeout_ms=10000)
    async def execute(
        self, action_type: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> str:
        from src.core.execution_contract import ExecutionContract, format_verification_report

        contract = ExecutionContract()
        params = kwargs or {}
        results = []

        if action_type == "file_write":
            file_path = params.get("file_path", "")
            expected = params.get("expected_content")
            results.append(contract.verify_file_write(file_path, expected))

        elif action_type == "git_commit":
            expected_msg = params.get("expected_message")
            results.append(contract.verify_git_commit(expected_msg))

        elif action_type == "git_push":
            results.append(contract.verify_git_push())

        elif action_type == "index_sync":
            project_root = params.get("project_root", "")
            results.append(contract.verify_index_sync(project_root))

        elif action_type == "all":
            file_path = params.get("file_path")
            if file_path:
                results.append(contract.verify_file_write(file_path))
            results.append(contract.verify_git_commit())
            results.append(contract.verify_git_push())

        else:
            return f"❌ Unknown action type: {action_type}"

        report = format_verification_report(results)
        return f"✅ Verification: {action_type}\n" + report


__all__ = [
    "SubmitBackgroundTaskTool",
    "GetTaskStatusTool",
    "VerifyActionTool",
]
