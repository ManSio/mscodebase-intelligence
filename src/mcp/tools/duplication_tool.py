"""find_duplicates — детектор дупликации кода (AST-отпечатки + minhash-LSH)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool


class FindDuplicatesTool(MCPTool):
    """find_duplicates — поиск copy-paste кода (exact + near-дубли).

    Метод: AST-нормализованные отпечатки (tree-sitter) + minhash-LSH.
    Возвращает группы точных дублей и пары ближних с similarity.
    """

    def __init__(self, services):
        super().__init__(services, tool_name="find_duplicates")

    @error_boundary("find_duplicates", timeout_ms=30000)
    async def execute(
        self,
        project_root: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.duplication import find_duplicates

        _kwargs = kwargs or {}
        target_path = (
            Path(project_root).resolve()
            if project_root
            else Path(self.resolve_indexer().project_path).resolve()
        )
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {target_path}"}

        try:
            threshold = float(_kwargs.get("threshold", 0.85))
        except (TypeError, ValueError):
            threshold = 0.85
        try:
            min_tokens = int(_kwargs.get("min_tokens", 24))
        except (TypeError, ValueError):
            min_tokens = 24

        return find_duplicates(
            target_path,
            threshold=threshold,
            min_tokens=min_tokens,
            max_results=int(_kwargs.get("max_results", 50)),
        )
