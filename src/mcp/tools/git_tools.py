"""Git-инструменты: get_branch_info, get_commit_history, get_file_history.

ИСПРАВЛЕНО (v2):
- Windows-safe subprocess: GIT_ASKPASS=echo + CREATE_NO_WINDOW
- CommitMemory синглтон (кэш на диске) — git log вызывается 1 раз за сессию
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.git_tools")


# ══════════════════════════════════════════════════════════
# Windows Git Safe Environment
# ══════════════════════════════════════════════════════════

def _get_git_env() -> dict:
    """Возвращает переменные окружения для безопасного вызова git на Windows.

    ★ КРИТИЧНО: на Windows git может зависнуть, пытаясь вызвать
    графический Credential Manager в скрытом процессе.
    Решение:
    - GIT_TERMINAL_PROMPT=0 — отключить интерактивные запросы
    - GIT_ASKPASS=echo — не вызывать askpass (credential helper)
    - GIT_PAGER=cat — не использовать pager
    """
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    env["GIT_PAGER"] = "cat"
    return env


def _get_subprocess_kwargs() -> dict:
    """Возвращает kwargs для subprocess с Windows-защитой.

    - CREATE_NO_WINDOW — не создавать окно консоли
    - stdout/stderr — PIPE для asyncio
    """
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": _get_git_env(),
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


async def _git_run(*args: str, cwd: Path, timeout: float = 15.0) -> str:
    """Выполняет git команду с защитой от зависания на Windows.

    Args:
        args: Аргументы команды (например: "git", "branch", "--show-current")
        cwd: Рабочая директория (корень проекта)
        timeout: Таймаут в секундах

    Returns:
        stdout команды (текст)

    Raises:
        subprocess.TimeoutError: Если команда не завершилась за timeout
        subprocess.CalledProcessError: Если команда вернула ненулевой код
    """
    logger.debug(f"[git] {' '.join(args)} (cwd={cwd})")

    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        **_get_subprocess_kwargs(),
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        # ★ КРИТИЧНО: убиваем процесс и всех дочерних при таймауте ★
        logger.error(f"[git] Timeout after {timeout}s: {' '.join(args)}")
        process.kill()
        await process.wait()
        raise

    if process.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace").strip()
        logger.warning(f"[git] Non-zero exit {process.returncode}: {error_msg}")
        raise subprocess.CalledProcessError(
            process.returncode, " ".join(args), output=stdout, stderr=stderr
        )

    return stdout.decode("utf-8", errors="replace").strip()


# ══════════════════════════════════════════════════════════
# Git Tools
# ══════════════════════════════════════════════════════════

class GetBranchInfoTool(MCPTool):
    """get_branch_info — информация о текущей git-ветке и индексе."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_branch_info")
        # Кэш BranchAwareIndex per project_path (избегаем повторных lancedb.connect)
        self._branch_index_cache: Dict[str, Any] = {}

    @error_boundary("get_branch_info", timeout_ms=10000)
    async def execute(
        self,
        project_root: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.search.branch_aware_index import BranchAwareIndex

        target_path = Path(project_root).resolve() if project_root else self.resolve_indexer().project_path
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {project_root}"}

        # Проверяем git-репозиторий
        if not (target_path / ".git").exists():
            return {
                "status": "error",
                "message": f"{target_path.name} is not a git repository",
            }

        # Используем кэш BranchAwareIndex чтобы не плодить соединения LanceDB
        target_str = str(target_path)
        if target_str not in self._branch_index_cache:
            bi = BranchAwareIndex(target_path)
            self._branch_index_cache[target_str] = bi
        else:
            bi = self._branch_index_cache[target_str]

        info = bi.get_branch_info()

        # Собираем список всех индексов веток
        all_indices = bi.list_branch_indices()

        return {
            "status": "ok",
            "branch": info["branch"],
            "db_path": info["db_path"],
            "index_exists": info["index_exists"],
            "total_chunks": info["total_chunks"],
            "all_branch_indices": all_indices,
        }


class GetCommitHistoryTool(MCPTool):
    """get_commit_history — история изменений проекта."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_commit_history")

    @error_boundary("get_commit_history", timeout_ms=15000)
    async def execute(
        self,
        project_root: str = "",
        limit: int = 10,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.commit_memory import CommitMemory

        target_path = Path(project_root).resolve() if project_root else self.resolve_indexer().project_path
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {target_path}"}

        # CommitMemory с кэшем на диске — git log вызывается 1 раз за сессию
        memory = CommitMemory(target_path)
        if not memory._commits:
            memory.fetch_commits(limit=limit)

        commits = memory._commits[:limit] if memory._commits else []
        stats = memory.get_stats()

        # Форматируем коммиты для ответа
        formatted = []
        for commit in commits:
            formatted.append({
                "hash": commit["hash"][:8],
                "date": commit.get("date", "")[:10],
                "message": commit.get("message", "")[:80],
                "files_changed": len(commit.get("files", [])),
                "author": commit.get("author", ""),
            })

        return {
            "status": "ok",
            "total_commits_in_history": stats["total"],
            "displayed": len(formatted),
            "commits": formatted,
            "authors": stats.get("authors", {}),
        }


class GetFileHistoryTool(MCPTool):
    """get_file_history — история изменений конкретного файла."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_file_history")

    @error_boundary("get_file_history", timeout_ms=15000)
    async def execute(
        self,
        project_root: str = "",
        file_path: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.commit_memory import CommitMemory

        target_path = Path(project_root).resolve() if project_root else self.resolve_indexer().project_path
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {target_path}"}

        if not file_path:
            return {"status": "error", "message": "file_path is required"}

        memory = CommitMemory(target_path)
        commits = memory.get_commits_for_file(file_path)
        stability = memory.get_file_stability(file_path)

        formatted = []
        for commit in commits[:10]:
            formatted.append({
                "hash": commit["hash"][:8],
                "date": commit.get("date", "")[:10],
                "message": commit.get("message", "")[:80],
            })

        # Если нет точных совпадений — показываем последние коммиты
        if not formatted:
            all_commits = memory.get_commits_for_file("")
            for commit in all_commits[:10]:
                formatted.append({
                    "hash": commit["hash"][:8],
                    "date": commit.get("date", "")[:10],
                    "message": commit.get("message", "")[:80],
                })
            return {
                "status": "ok",
                "file": file_path,
                "note": "Нет точных совпадений. Показаны последние коммиты.",
                "commits": formatted,
            }

        return {
            "status": "ok",
            "file": file_path,
            "stability": stability["stability"],
            "change_count": stability["change_count"],
            "commits": formatted,
        }


__all__ = [
    "GetBranchInfoTool",
    "GetCommitHistoryTool",
    "GetFileHistoryTool",
    "_git_run",
    "_get_git_env",
    "_get_subprocess_kwargs",
]
