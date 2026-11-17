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

    @error_boundary("find_duplicates", timeout_ms=120000)
    async def execute(
        self,
        project_root: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.duplication import find_duplicates
        from src.mcp.notifications import bind_session_from_request

        # Без захвата сессии прогресс некуда отправлять (аудит 2026-11-17).
        bind_session_from_request()

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

        import asyncio

        from src.mcp import notifications as _notify

        try:
            max_files = int(_kwargs.get("max_files", 1000))
        except (TypeError, ValueError):
            max_files = 1000

        # Скан — синхронный и тяжёлый: в поток, чтобы не блокировать сервер
        # и чтобы `error_boundary` мог сработать (замер 2026-11-17: 73 с).
        loop = asyncio.get_running_loop()

        def _progress(current, total, phase="parsed"):
            try:
                _notify.schedule(
                    _notify.notify_log(
                        "info",
                        f"find_duplicates: просканировано {current} файлов",
                        "mscodebase.duplication",
                    ),
                    loop,
                )
            except Exception:  # noqa: BLE001 — прогресс не критичен
                pass

        result = await asyncio.to_thread(
            find_duplicates,
            target_path,
            threshold=threshold,
            min_tokens=min_tokens,
            max_results=int(_kwargs.get("max_results", 50)),
            max_files=max_files,
            progress_cb=_progress,
        )
        files_scanned = result.get("files_scanned", 0)
        if files_scanned >= max_files:
            result["truncated"] = True
            result["next_step"] = (
                f"Просканировано {files_scanned} файлов (лимит max_files={max_files}). "
                f"Увеличьте max_files или сузьте проект."
            )
        return result
