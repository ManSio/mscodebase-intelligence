"""
codebase_tool.py — Единый интерфейс для всех операций с кодом.

Реализует «Hub & Spoke» архитектуру:
- codebase(action, ...) — стабильные примитивы (read/write/index/git/system)
- execute_python_script(code) — E2B-песочница для всего остального
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.codebase")


# ══════════════════════════════════════════════════════════
# Слой 1: Стабильные примитивы (Hub)
# ══════════════════════════════════════════════════════════


class CodebaseTool(MCPTool):
    """Единый интерфейс для работы с кодовой базой.

    Доступные action:
    - "write"      — rename/ack/move/delete/replace/insert символы
    - "index"      — notify_change/reindex/status/progress
    - "git"        — log/history/branch
    - "system"     — health/logs/read/counters

    Примеры:
      codebase(action="write", old_name="foo", new_name="bar")  # rename
      codebase(action="index", path="src/main.py")              # notify
      codebase(action="git", path=".")                          # log
      codebase(action="system", path="health")                  # health
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="codebase")
        self._services = services

    @error_boundary("codebase", timeout_ms=30000)
    async def execute(
        self,
        action: str = "",
        # write params
        old_name: str = "",
        new_name: str = "",
        symbol: str = "",
        to_file: str = "",
        new_code: str = "",
        anchor_symbol: str = "",
        # general
        path: str = "",
        file_path: str = "",
        apply: bool = False,
        force: bool = False,
        allow_collision: bool = False,
        # index
        project_root: str = "",
        # git
        max_count: int = 10,
    ) -> str:
        """Execute a codebase operation.

        Args:
            action: 
                "write" — символьные операции (rename/move/delete/etc)
                "index" — управление индексацией (notify/reindex/status)
                "git"   — git история (log/history/branch)
                "system" — системные запросы (health/logs/read)
            old_name: исходное имя символа (write/rename)
            new_name: новое имя символа (write/rename)
            symbol: имя символа (write/move/delete)
            to_file: целевой файл (write/move)
            new_code: новый код (write/replace/insert)
            anchor_symbol: символ-якорь (insert_before/after)
            path: файл или запрос (index notify / system health)
            file_path: файл для операции
            apply: применить изменения (False = предпросмотр)
            force: принудительно (write/delete)
            allow_collision: разрешить коллизию имён (write/rename)
            project_root: корень проекта (index)
            max_count: лимит результатов (git)
        """
        action_map = {
            "write": self._action_write,
            "index": self._action_index,
            "git": self._action_git,
            "system": self._action_system,
        }
        handler = action_map.get(action)
        if not handler:
            return (
                f"🚫 Unknown action: '{action}'. "
                f"Available: write, index, git, system"
            )
        return await handler(**locals())

    async def _action_write(self, **kw) -> str:
        """Write operations — делегирует в WriteTool."""
        from src.mcp.tools.write_tools import WriteTool

        wt = WriteTool(self._services)
        d = kw.copy()
        # Определяем поддействие по наличию параметров
        if d.get("old_name") and d.get("new_name"):
            sub_action = "rename"
        elif d.get("symbol") and d.get("to_file"):
            sub_action = "move"
        elif d.get("symbol") and d.get("new_code"):
            sub_action = "replace"
        elif d.get("symbol") and d.get("force") is not None:
            sub_action = "safe_delete"
        elif d.get("anchor_symbol") and d.get("new_code"):
            sub_action = "insert_before"  # default to before
        elif d.get("symbol") or d.get("file_path"):
            sub_action = "ack"
        else:
            return "🚫 Provide old_name+new_name (rename) or symbol+to_file (move)"
        return await wt.execute(action=sub_action, **{
            k: v for k, v in d.items() 
            if k in ('old_name','new_name','symbol','to_file','new_code',
                     'anchor_symbol','file_path','apply','force','allow_collision')
        })

    async def _action_index(self, **kw) -> str:
        """Index operations — делегирует в IndexTool."""
        from src.mcp.tools.meta_tools import IndexTool

        path = kw.get("path") or kw.get("project_root") or ""
        it = IndexTool(self._services)
        # Определяем поддействие
        if kw.get("new_code") or kw.get("old_name"):
            sub = "notify"
        elif path and path.endswith("/"):
            sub = "reindex"
        else:
            sub = "status"
        return await it.execute(action=sub, project_root=path)

    async def _action_git(self, **kw) -> str:
        """Git operations — делегирует в GitTool."""
        from src.mcp.tools.meta_tools import GitTool

        path = kw.get("path", ".")
        gt = GitTool(self._services)
        return await gt.execute(action="log", path=path, max_count=kw.get("max_count", 10))

    async def _action_system(self, **kw) -> str:
        """System operations — делегирует в SystemTool."""
        from src.mcp.tools.meta_tools import SystemTool

        path = kw.get("path", "health")
        st = SystemTool(self._services)
        return await st.execute(action=path)


# ══════════════════════════════════════════════════════════
# Слой 2: E2B-песочница (Spoke)
# ══════════════════════════════════════════════════════════


class ExecuteScriptTool(MCPTool):
    """Выполняет Python-код в изолированной среде.

    Позволяет агенту решать задачи, для которых нет готового инструмента.
    Агент пишет код, сервер выполняет его и возвращает результат.

    Примеры использования:
      - Подсчёт строк в файлах
      - Поиск паттернов (grep своими руками)
      - Пакетные операции над файлами
      - Кастомный анализ кода

    Ограничения:
      - Таймаут: 60 секунд
      - Нет доступа к сети (по умолчанию)
      - Нет доступа к sys.modules MCP-сервера
      - Результат: stdout + stderr (до 10000 символов)
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="execute_script")

    @error_boundary("execute_script", timeout_ms=65000)
    async def execute(
        self,
        code: str,
        timeout: int = 30,
        args: str = "",
    ) -> str:
        """Execute Python code in a sandboxed environment.

        Args:
            code: Python code to execute
            timeout: Max execution time in seconds (5-120)
            args: Command-line arguments (passed as sys.argv)

        Returns:
            stdout + stderr output (truncated to 10000 chars)
        """
        if not code.strip():
            return "🚫 **Error:** Empty code."

        timeout = max(5, min(timeout, 120))

        # Создаём временный файл
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            script_path = f.name

        try:
            # Запускаем в subprocess с таймаутом
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**{k: v for k, v in dict(
                    PATH=__import__('os').environ.get('PATH', ''),
                    PYTHONPATH=str(Path(__file__).resolve().parent.parent.parent),
                ).items()}},
                cwd=str(Path.cwd()),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"⏱ **Timeout** ({timeout}s)\n```\n{code[:200]}...\n```"

            out = (stdout or b"").decode("utf-8", errors="replace")
            err = (stderr or b"").decode("utf-8", errors="replace")

            # Обрезаем до 10000 символов
            result = ""
            if out:
                result += f"**stdout:**\n```\n{out[:5000]}\n```\n"
            if err:
                result += f"**stderr:**\n```\n{err[:5000]}\n```\n"
            if not result:
                result = "_Выполнено (нет вывода)_"

            summary = f"✅ **Script executed** (exit={proc.returncode}, {timeout}s timeout)\n\n{result}"
            return summary

        except Exception as e:
            return f"🚫 **Error:** {e}"
        finally:
            Path(script_path).unlink(missing_ok=True)


__all__ = ["CodebaseTool", "ExecuteScriptTool"]
