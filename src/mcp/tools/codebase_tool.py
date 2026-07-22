"""
codebase_tool.py — Единый интерфейс для всех операций с кодом.

Реализует «Hub & Spoke» архитектуру:
- codebase(action, ...) — стабильные примитивы (read/write/index/git/system)
- execute_script(code) — выполнение Python-кода (host-based, без изоляции)"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

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
        old_name: str = "",
        new_name: str = "",
        symbol: str = "",
        to_file: str = "",
        new_code: str = "",
        anchor_symbol: str = "",
        path: str = "",
        file_path: str = "",
        apply: bool = False,
        force: bool = False,
        allow_collision: bool = False,
        project_root: str = "",
        max_count: int = 10,
    ) -> str:
        """Hub: диспетчеризация по action в профильные инструменты."""
        action_map = {
            "write": self._action_write,
            "index": self._action_index,
            "git": self._action_git,
            "system": self._action_system,
        }
        handler = action_map.get(action)
        if not handler:
            return (
                f"❌ Unknown action `{action}`. "
                f"Available: {', '.join(action_map)}"
            )
        kw = {k: v for k, v in locals().items() if k not in ('self', 'handler', 'action_map')}
        return await handler(**kw)

    async def _action_write(self, **kw) -> str:
        """Write operations — делегирует в SymbolWriteTool."""
        from src.mcp.tools.symbol_write_tools import SymbolWriteTool

        wt = SymbolWriteTool(self._services)
        # Пробрасываем только нужные kwargs
        return await wt.execute(
            action=kw.get("action", ""),
            old_name=kw.get("old_name", ""),
            new_name=kw.get("new_name", ""),
            symbol=kw.get("symbol", ""),
            to_file=kw.get("to_file", ""),
            new_code=kw.get("new_code", ""),
            anchor_symbol=kw.get("anchor_symbol", ""),
            file_path=kw.get("file_path", ""),
            apply=kw.get("apply", False),
            force=kw.get("force", False),
            allow_collision=kw.get("allow_collision", False),
            project_root=kw.get("project_root", ""),
        )

    async def _action_index(self, **kw) -> str:
        """Index operations — делегирует в IndexTool."""
        from src.mcp.tools.index_tools import IndexTool

        it = IndexTool(self._services)
        return await it.execute(
            action=kw.get("action", ""),
            path=kw.get("path", ""),
            project_root=kw.get("project_root", ""),
        )

    async def _action_git(self, **kw) -> str:
        """Git operations — делегирует в GitTool."""
        from src.mcp.tools.git_tools import GitTool

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
# Слой 2: Host-based execution (Spoke, без sandbox)
# ══════════════════════════════════════════════════════════


class ExecuteScriptTool(MCPTool):
    """Выполняет Python-код на хосте (host-based execution).

    ⚠️ ВНИМАНИЕ: Изоляция (sandbox) ОТСУТСТВУЕТ.
    Код выполняется с правами пользователя Zed, имеет полный доступ
    к файловой системе, процессам и сети хоста.

    Инструмент ОТКЛЮЧЁН ПО УМОЛЧАНИЮ.
    Включение: MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true в .env
    (см. .env.example). Перед включением убедитесь, что понимаете
    риски выполнения произвольного кода на хосте.

    Возвращает структурированный результат:
    - stdout / stderr (с маркером обрезки)
    - exit_code, duration_ms, truncated flags
    - TEMP_DIR в env для временных файлов скрипта
    - PYTHONPATH = project root (чтобы import src.xxx работал)
    - PATH = "" (очищен, дочерние процессы не найдут cmd/powershell)
    """

    _STDOUT_LIMIT = 5000
    _STDERR_LIMIT = 5000

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="execute_script")

    # ── helpers ────────────────────────────────────────────────

    @staticmethod
    def _truncate(text: str, limit: int, label: str = "output") -> str:
        """Обрезает текст с маркером, если превышен лимит."""
        if len(text) <= limit:
            return text
        return (
            text[:limit]
            + f"\n... [TRUNCATED at {limit} chars; total {len(text)} chars]"
        )

    @staticmethod
    def _build_env(project_root: str) -> dict:
        """Строит чистое окружение для скрипта.

        PATH="" — дочерний процесс не находит cmd.exe, powershell.exe,
        curl.exe и другие системные утилиты. Это не sandbox, но снижает
        поверхность атаки при инъекциях.
        """
        env = {
            "PATH": "",
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PYTHONPATH": project_root,
        }
        return env

    @staticmethod
    async def _graceful_shutdown(proc) -> None:
        """Graceful shutdown: term -> sleep -> kill.

        Паттерн из CPython docs: Popen.communicate(timeout=15).
        """
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
                return
            except (asyncio.TimeoutError, RuntimeError):
                pass
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:
            pass

    @staticmethod
    def _format_result(result: dict) -> str:
        """Форматирует structured result в человекочитаемую строку."""
        exit_code = result["exit_code"]
        duration = result["duration_ms"]
        status_icon = "\u2705" if exit_code == 0 else "\u26a0\ufe0f"

        lines = [
            f"{status_icon} **Script executed** "
            f"(exit={exit_code}, {duration}ms)"
        ]

        out = result.get("stdout", "")
        err = result.get("stderr", "")

        if out:
            lines.append(f"\n**stdout:\n```\n{out}\n```")
        if err:
            lines.append(f"\n**stderr:\n```\n{err}\n```")
        if not out and not err:
            lines.append("\n_Выполнено (нет вывода)_")

        if result.get("truncated"):
            lines.append("\n_\u26a0\ufe0f Output was truncated_")
        if result.get("timed_out"):
            lines.append(f"\n_\u23f1 Timed out at {result.get('timeout_s', '?')}s_")

        return "\n".join(lines)

    # ── main execution ─────────────────────────────────────────

    @error_boundary("execute_script", timeout_ms=140000)
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
            Structured dict:
            {stdout, stderr, exit_code, duration_ms, truncated, timed_out}
        """
        if not code.strip():
            return json.dumps({
                "stdout": "",
                "stderr": "Empty code.",
                "exit_code": 1,
                "duration_ms": 0,
                "truncated": False,
                "timed_out": False,
            })

        timeout = max(5, min(timeout, 120))
        project_root = str(Path.cwd())
        t0 = time.perf_counter()

        # Windows: не показывать окно cmd
        startupinfo = None
        creationflags = 0
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW

        with tempfile.TemporaryDirectory(prefix="mscx_exec_") as tmp_dir:
            env = self._build_env(project_root)
            env["TEMP_DIR"] = tmp_dir
            env["TMP"] = tmp_dir

            timed_out = False
            exit_code = 0
            stdout_text = ""
            stderr_text = ""

            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-c", code,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=tmp_dir,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                    close_fds=True,
                )

                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    timed_out = True
                    await self._graceful_shutdown(proc)
                    exit_code = -1

                if not timed_out:
                    stdout_text = (stdout_bytes or b"").decode("utf-8", errors="replace")
                    stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")
                    exit_code = proc.returncode or 0

            except Exception as e:
                duration_ms = round((time.perf_counter() - t0) * 1000, 1)
                return json.dumps({
                    "stdout": "",
                    "stderr": str(e),
                    "exit_code": 1,
                    "duration_ms": duration_ms,
                    "truncated": False,
                    "timed_out": False,
                })

            duration_ms = round((time.perf_counter() - t0) * 1000, 1)

            stdout_truncated = len(stdout_text) > self._STDOUT_LIMIT
            stderr_truncated = len(stderr_text) > self._STDERR_LIMIT
            stdout_shown = self._truncate(stdout_text, self._STDOUT_LIMIT, "stdout")
            stderr_shown = self._truncate(stderr_text, self._STDERR_LIMIT, "stderr")

            raw = {
                "stdout": stdout_shown,
                "stderr": stderr_shown,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "truncated": stdout_truncated or stderr_truncated,
                "timed_out": timed_out,
            }
            if timed_out:
                raw["timeout_s"] = timeout

            return self._format_result(raw)
