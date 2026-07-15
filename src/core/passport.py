"""
Passport — Runtime Process Passport (RUN_ID, BUILD_ID, PID, started_at).

ЕТО ЕДИНСТВЕННОЕ МЕСТО, где определены runtime-переменные процесса.
server.py импортирует их отсюда, а не наоборот.

Это решает архитектурный инвариант:
  Core слой (src/core/) НЕ импортирует src.mcp.

Usage:
    from src.core.passport import RUN_ID, RUN_PID, RUN_STARTED_AT, BUILD_ID
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from pathlib import Path

# ══════════════════════════════════════════════════════════════
# Runtime Identity
# ══════════════════════════════════════════════════════════════

RUN_ID: str = uuid.uuid4().hex[:12]
"""Уникальный ID запуска (12 hex символов). Меняется при каждом старте MCP."""

RUN_STARTED_AT: float = time.time()
"""Unix timestamp старта процесса."""

RUN_PID: int = os.getpid()
"""PID текущего процесса."""

RUN_SOURCE_FILE: str = str(Path(__file__).resolve())
"""Путь к файлу passport.py (для диагностики)."""


# ══════════════════════════════════════════════════════════════
# Build Identity (git commit hash)
# ══════════════════════════════════════════════════════════════

BUILD_ID: str = ""
"""Git commit hash (первые 12 символов). Пустая строка если git недоступен."""

try:
    _git_dir = Path(__file__).resolve().parent.parent.parent / ".git"
    if _git_dir.is_dir():
        _head = _git_dir / "HEAD"
        if _head.exists():
            _ref = _head.read_text("utf-8").strip()
            if _ref.startswith("ref: "):
                _ref_path = _git_dir / _ref[5:]
                if _ref_path.exists():
                    BUILD_ID = _ref_path.read_text("utf-8").strip()[:12]
            else:
                BUILD_ID = _ref[:12]
except Exception as _e:
    logger.warning("exception", exc_info=True)
    pass
def get_uptime() -> float:
    """Секунд с момента старта процесса."""
    return time.time() - RUN_STARTED_AT


def to_dict() -> dict:
    """Сериализация в dict (для debug_runtime_passport)."""
    return {
        "run_id": RUN_ID,
        "build_id": BUILD_ID or "<no git>",
        "pid": RUN_PID,
        "started_at": datetime.fromtimestamp(RUN_STARTED_AT).isoformat(),
        "uptime_sec": round(get_uptime(), 1),
        "source_file": RUN_SOURCE_FILE,
    }
