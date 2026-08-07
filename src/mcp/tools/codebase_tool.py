"""
codebase_tool.py — Единый интерфейс для всех операций с кодом.

Реализует «Hub & Spoke» архитектуру:
- codebase(action, ...) — стабильные примитивы (read/write/index/git/system)
- execute_script(code) — выполнение Python-кода (host-based, без изоляции)

E2E-LIVE-2026-08-03: проверка on-the-fly видимости правок в индексе."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.codebase")


# ══════════════════════════════════════════════════════════
# Слой 1: Стабильные примитивы (Hub)
# ══════════════════════════════════════════════════════════


class CodebaseTool(MCPTool):
    """Единый интерфейс для работы с кодовой базой.

    Доступные action (контракт README, все 3 языка):
    - Write-под-действия: "rename" | "move" | "safe_delete" | "replace" |
      "insert_before" | "insert_after" | "ack_impact" (→ WriteTool)
    - "write"      — legacy umbrella: под-действие выводится из kwargs
    - "index"      — notify_change/reindex/status/progress
    - "git"        — log/history/branch
    - "system"     — health/logs/read/counters

    Примеры:
      codebase(action="rename", old_name="foo", new_name="bar", apply=False)
      codebase(action="move", symbol="Foo", to_file="src/b.py", apply=False)
      codebase(action="replace", symbol="Foo", new_code="...", apply=False)
      codebase(action="insert_before", anchor_symbol="Bar", new_code="...")
      codebase(action="ack_impact", file_path="src/main.py", impact_token="...")
      codebase(action="write", old_name="foo", new_name="bar")  # legacy rename
      codebase(action="index", path="status")                   # get_index_status
      codebase(action="index", path="notify", file_path="src/main.py")  # notify_change
      codebase(action="git", path=".")                          # log
      codebase(action="system", path="health")                  # health

    Под-действия index (path): status | progress | timeline | health |
    project_dir | notify.
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
        impact_token: str = "",
    ) -> str | dict[str, Any]:
        """Hub: диспетчеризация по action в профильные инструменты."""
        action_map: dict[str, Any] = {
            "write": self._action_write,  # legacy umbrella: вывод из kwargs
            "rename": self._action_write,
            "ack": self._action_write,
            "ack_impact": self._action_write,
            "delete": self._action_write,
            "safe_delete": self._action_write,
            "move": self._action_write,
            "replace": self._action_write,
            "insert_before": self._action_write,
            "insert_after": self._action_write,
            "symbol": self._action_symbol,  # BS-13: граф вызовов символа
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
        # Explicit kwargs — avoids inspect.signature + locals() antipattern
        # which fails for **kw methods (passes self, handler, action_map etc.)
        _dispatch = {
            "action": action, "old_name": old_name, "new_name": new_name,
            "symbol": symbol, "to_file": to_file, "new_code": new_code,
            "anchor_symbol": anchor_symbol, "path": path, "file_path": file_path,
            "apply": apply, "force": force, "allow_collision": allow_collision,
            "project_root": project_root, "max_count": max_count,
            "impact_token": impact_token,
        }
        return await handler(**_dispatch)

    async def _action_write(self, **kw) -> str:
        """Write operations — делегирует в WriteTool.

        Под-действие определяется:
        1. Из явного action (rename/move/safe_delete/replace/insert_*/ack_impact);
        2. Для legacy action="write" — выводится из переданных kwargs.
        """
        sub = (kw.get("action") or "").strip().lower()
        sub = _WRITE_ACTION_ALIASES.get(sub, sub)
        if sub in ("", "write"):
            sub = _infer_write_subaction(kw)
        if sub not in _WRITE_ACTIONS:
            return (
                f"❌ Не удалось определить write sub-action "
                f"(action={kw.get('action')!r}). Документированные формы (README): "
                f"codebase(action='rename'|'move'|'safe_delete'|'replace'|"
                f"'insert_before'|'insert_after'|'ack_impact', ...) или legacy "
                f"codebase(action='write', old_name=..., new_name=...)."
            )

        from src.mcp.tools.write_tools import WriteTool

        wt = WriteTool(self._services)
        # Пробрасываем только нужные kwargs. project_root НЕ принимается
        # WriteTool.execute — убран (REF: symbol_write_tools → write_tools).
        return await wt.execute(
            action=sub,
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
            impact_token=kw.get("impact_token", ""),
        )

    async def _action_symbol(self, **kw) -> str:
        """Symbol operations — граф вызовов символа (эквивалент get_symbol_info).

        BS-13 (аудит Bot_snow): action="symbol" отсутствовал в hub —
        символьные запросы были недостижимы через codebase().
        """
        from src.mcp.tools.search_tools import GetSymbolInfoTool

        st = GetSymbolInfoTool(self._services)
        return await st.execute(query=kw.get("symbol", ""))

    async def _action_index(self, **kw) -> str | dict[str, Any]:
        """Index operations — диспетчеризация по path к системным index-инструментам.

        Под-действие выбирается параметром path:
          "" | "status"   → get_index_status
          "progress"      → get_index_progress
          "timeline"      → get_index_timeline
          "health"        → index_health (project_root = целевой проект)
          "project_dir"   → index_project_dir (project_root = целевой путь)
          "notify"        → notify_change (file_path = целевой файл)

        Ранее импортировался несуществующий src.mcp.tools.index_tools —
        канал падал ImportError'ом. Теперь делегируем в реальные классы.
        """
        sub = (kw.get("path") or "").strip().lower()
        from src.mcp.tools.indexing_tools import (
            IndexHealthTool,
            IndexProjectDirTool,
            NotifyChangeTool,
        )
        from src.mcp.tools.system_tools import (
            GetIndexProgressTool,
            GetIndexStatusTool,
            GetIndexTimelineTool,
        )

        services = self._services
        if sub in ("", "status"):
            return await GetIndexStatusTool(services).execute()
        if sub == "progress":
            return await GetIndexProgressTool(services).execute()
        if sub == "timeline":
            return await GetIndexTimelineTool(services).execute()
        if sub == "health":
            return await IndexHealthTool(services).execute(
                project_root=kw.get("project_root", "")
            )
        if sub == "project_dir":
            target = kw.get("project_root") or kw.get("path")
            if not target:
                return "❌ index_project_dir: required project_root (целевой путь)"
            return await IndexProjectDirTool(services).execute(path=target)
        if sub == "notify":
            file_path = kw.get("file_path", "")
            if not file_path:
                return "❌ notify_change: required file_path (путь к файлу)"
            return await NotifyChangeTool(services).execute(file_path=file_path)
        return (
            f"❌ Unknown index sub-action: '{sub}'. "
            f"Available: status | progress | timeline | health | project_dir | notify"
        )

    async def _action_git(self, **kw) -> str | dict[str, Any]:
        """Git operations — делегирует в GetCommitHistoryTool."""
        from src.mcp.tools.git_tools import GetCommitHistoryTool

        path = kw.get("path", ".")
        gt = GetCommitHistoryTool(self._services)
        return await gt.execute(project_root=path, limit=kw.get("max_count", 10))

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
    """Выполняет Python-код на хосте (host-based execution) в песочнице.

    Код выполняется через execute_sandboxed() с AST-валидацией,
    allowlist безопасных модулей и изоляцией subprocess.
    Режим песочницы определяется переменной MSCODEBASE_SANDBOX_MODE
    (по умолчанию SANDBOX_MODE_STRICT).

    ⚠️ ВНИМАНИЕ: Sandbox изолирует код от опасных операций
    (импорт sys/os/subprocess, запись за пределы temp-dir и т.д.)
    но НЕ обеспечивает полной изоляции от хоста. Код выполняется
    с правами пользователя Zed.

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

        Security layers:
        1. AST validation — blocks dangerous patterns before execution
        2. Module allowlist — only safe stdlib modules permitted
        3. Subprocess isolation — code runs in separate process with restricted env
        4. Timeout enforcement — kills long-running code
        5. Audit logging — every execution logged

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

        # Determine sandbox mode from env
        from src.core.sandbox.executor import (
            SANDBOX_MODE_OFF,
            SANDBOX_MODE_PERMISSIVE,
            SANDBOX_MODE_STRICT,
            execute_sandboxed,
        )
        sandbox_mode = os.environ.get(
            "MSCODEBASE_SANDBOX_MODE", SANDBOX_MODE_STRICT
        )
        # SEC-5: валидируем значение env — мусор не должен молча
        # ломать песочницу (например, "none" вместо "off" → strict-ветка
        # не выполнится, а режим будет не тем, что ожидалось).
        if sandbox_mode not in (SANDBOX_MODE_STRICT, SANDBOX_MODE_PERMISSIVE, SANDBOX_MODE_OFF):
            logger.warning(
                f"MSCODEBASE_SANDBOX_MODE={sandbox_mode!r} невалиден, "
                f"использую {SANDBOX_MODE_STRICT}"
            )
            sandbox_mode = SANDBOX_MODE_STRICT

        # Parse args string into list
        arg_list = args.split() if args else []

        # Execute in sandbox
        result = await asyncio.to_thread(
            execute_sandboxed,
            code=code,
            timeout=timeout,
            project_root=project_root,
            mode=sandbox_mode,
            args=arg_list,
        )

        # Format for display
        raw = {
            "stdout": self._truncate(result.get("stdout", ""), self._STDOUT_LIMIT, "stdout"),
            "stderr": self._truncate(result.get("stderr", ""), self._STDERR_LIMIT, "stderr"),
            "exit_code": result.get("exit_code", 1),
            "duration_ms": result.get("duration_ms", 0),
            "truncated": result.get("truncated", False),
            "timed_out": result.get("timed_out", False),
        }
        if result.get("timed_out"):
            raw["timeout_s"] = timeout
        if result.get("violation"):
            raw["stderr"] = f"🔒 Sandbox violation: {result['violation']}\n{raw['stderr']}"

        return self._format_result(raw)


# ══════════════════════════════════════════════════════════
# Write sub-action aliases (README-контракт → WriteTool.action).
# "delete" — синоним safe_delete; "ack_impact" — README-форма ack.
# ══════════════════════════════════════════════════════════
_WRITE_ACTION_ALIASES = {
    "delete": "safe_delete",
    "ack_impact": "ack",
}
_WRITE_ACTIONS = {
    "rename", "ack", "move", "safe_delete", "replace",
    "insert_before", "insert_after",
}


def _infer_write_subaction(kw: dict) -> str:
    """Выводит под-действие write из переданных kwargs (legacy "write")."""
    if kw.get("old_name") and kw.get("new_name"):
        return "rename"
    if kw.get("symbol") and kw.get("to_file"):
        return "move"
    if kw.get("anchor_symbol") and kw.get("new_code"):
        return "insert_before"
    if kw.get("symbol") and kw.get("new_code"):
        return "replace"
    if kw.get("symbol"):
        return "safe_delete"
    if kw.get("file_path"):
        return "ack"
    return ""
