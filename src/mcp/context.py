"""Контекст MCP-рантайма — состояние и хелперы, общие для server/factory/tools.

Создан 2026-08-17 (прототип A+B, ARCLUX audit: кластер циклических импортов
server↔server_factory↔server_tools↔tools/*, 24/29 циклов).

Зачем этот модуль:
- `_default_project_root` / `_services_cache` / `_RUN_SOURCE_FILE` / `_BUILD_ID`
  были модульным состоянием server.py; server_factory (10 мест), server_tools
  (3 места) и tools/* (6 файлов) импортировали их из server — это замыкало
  циклы server↔factory↔tools.
- Перенос состояния в ОТДЕЛЬНЫЙ модуль src/mcp/ (а не в src/core) соблюдает
  ARCH-03 (core не знает про mcp-runtime): `_services_cache` держит DI-сервисы
  MCP, это не core-концепция.
- server.py остаётся тонким фасадом: реэкспортирует имена отсюда и из core
  для обратной совместимости (`from src.mcp.server import _ext_root` и т.п.).

Направление импортов: context ← {server, server_factory, server_tools, tools/*}
(только входящие, context не импортирует никого из mcp — кроме core).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.core.passport import (
    RUN_ID as _RUN_ID,
)
from src.core.passport import (
    RUN_PID as _RUN_PID,
)
from src.core.passport import (
    RUN_STARTED_AT as _RUN_STARTED_AT,
)
from src.core.project_resolution import (
    ext_root as _ext_root,
)

logger = logging.getLogger("mscodebase_server")

# ══════════════════════════════════════════════════════════
# Runtime-состояние (ранее — модульное состояние server.py)
# ══════════════════════════════════════════════════════════

# Default project root (устанавливается при create_mcp_server)
_default_project_root: Optional[Path] = None
_services_cache: Optional[Any] = None  # для debug_runtime_passport

# Source file идентичности процесса (был server.py — теперь контекст-модуль)
_RUN_SOURCE_FILE = str(Path(__file__).resolve())

# BUILD_ID — git commit hash для мгновенной верификации версии кода.
_BUILD_ID: str = ""
try:
    _git_dir = Path(__file__).resolve().parent.parent.parent / ".git"
    if _git_dir.is_dir():
        _head = _git_dir / "HEAD"
        if _head.exists():
            _ref = _head.read_text("utf-8").strip()
            if _ref.startswith("ref: "):
                _ref_path = _git_dir / _ref[5:]
                if _ref_path.exists():
                    _BUILD_ID = _ref_path.read_text("utf-8").strip()[:12]
            else:
                _BUILD_ID = _ref[:12]
except Exception as _e:  # noqa: BLE001 — диагностика не должна падать при старте
    logger.warning(f"BUILD_ID detection failed: {_e}")


# ══════════════════════════════════════════════════════════
# Хелперы запуска (ранее — функции server.py)
# ══════════════════════════════════════════════════════════


def _log_run_passport() -> None:
    """Печатает 'паспорт' процесса при старте — уникальный RUN_ID + BUILD_ID + env summary.

    Это позволяет мгновенно отличить старый процесс от нового при отладке,
    и подтвердить, что Zed подхватил обновлённый код.
    """
    import getpass

    _bridge_state = "<not used — LSP server removed 2026-07-20>"
    _registry_state = "<unavailable>"
    try:
        from src.core.di_container import ProjectIndexerRegistry as PIRKey

        if _services_cache is not None:
            _reg = _services_cache.resolve(PIRKey)
            _paths = _reg.get_all_paths()
            _registry_state = "; ".join(str(p) for p in _paths) if _paths else "<empty>"
    except Exception as _e:  # noqa: BLE001
        logger.warning(f"Registry state check failed: {_e}")
    import os

    lines = [
        "",
        "=" * 60,
        "MSCodeBase Intelligence — Process Passport",
        f"  RUN_ID      : {_RUN_ID}",
        f"  BUILD_ID    : {_BUILD_ID or '<no git>'}",
        f"  PID         : {_RUN_PID}",
        f"  Started at  : {datetime.fromtimestamp(_RUN_STARTED_AT).isoformat()}",
        f"  Source file : {_RUN_SOURCE_FILE}",
        f"  User        : {getpass.getuser()}",
        f"  CWD         : {Path.cwd().resolve()}",
        f"  _ext_root   : {_ext_root}",
        f"  PROJECT_PATH     env: {os.environ.get('PROJECT_PATH', '<unset>')!r}",
        f"  ZED_WORKTREE_ROOT env: {os.environ.get('ZED_WORKTREE_ROOT', '<unset>')!r}",
        f"  MSCODEBASE_ALLOW_SELF_INDEX env: {os.environ.get('MSCODEBASE_ALLOW_SELF_INDEX', '<unset>')!r}",
        f"  PYTHONPATH env[0] : {(os.environ.get('PYTHONPATH') or '').split(os.pathsep)[0]!r}",
        f"  Bridge      : {_bridge_state}",
        f"  Registry    : {_registry_state}",
        "=" * 60,
        "",
    ]
    for ln in lines:
        logger.info(ln)


def _check_source_extension_sync() -> Optional[str]:
    """DEV-ONLY: проверяет рассинхрон source↔extension.

    Читает .codebase_indices/install_meta.json (записанный install.py в dev-режиме).
    Сверяет git HEAD исходников с записанным.
    Возвращает warning-строку или None.

    Обычные пользователи: install_meta.json отсутствует → возвращает None.
    """
    try:
        meta_path = Path(".codebase_indices") / "install_meta.json"
        if not meta_path.exists():
            return None  # не dev-режим — не проверяем

        import json
        import subprocess

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        installed_head = meta.get("git_head")
        if not installed_head:
            return None

        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode == 0:
            current_head = r.stdout.strip()
            if current_head != installed_head:
                return (
                    f"⚠️ Исходники обновлены (git {current_head[:8]} ≠ "
                    f"установлено {installed_head[:8]}). Запустите install.py "
                    f"для синхронизации расширения."
                )
        return None
    except Exception as _git_err:  # noqa: BLE001 — чисто диагностический sync-check
        logger.debug(f"Git version check failed: {_git_err}")
        return None
