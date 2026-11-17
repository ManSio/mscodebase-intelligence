"""Read-only режим второго сервера: запись обязана падать, а не молчать.

Логи: 621 `База занята другим процессом MCP — работаю read-only` и 280
`PID lock held ... waiting`. Решение 2026-11-17 — поведение не менять, но
зафиксировать инвариант тестом: второй менеджер на тот же каталог не пишет.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.indexing.db_manager import LanceDBManager


def _manager(root: Path) -> LanceDBManager:
    project = root / "project"
    project.mkdir(parents=True, exist_ok=True)
    return LanceDBManager(
        db_path=root / "index.lancedb",
        embedder=None,
        project_path=project,
        embedding_dim=768,
    )


def test_second_manager_is_read_only_and_write_fails_loudly(tmp_path):
    owner = _manager(tmp_path)
    try:
        second = _manager(tmp_path)
        try:
            assert second._startup_issue is not None, "второй менеджер не увидел lock"
            assert "read-only" in second._startup_issue
            with pytest.raises(Exception) as exc:
                with second.begin_write():
                    pass
            err = exc.value
            # Типизированный отказ (ErrorCode.DATABASE_LOCKED), а не голый RuntimeError.
            assert getattr(err, "code", "") == "DATABASE_LOCKED"
            assert getattr(err, "recoverable", False) is True
            assert "занята другим процессом" in str(getattr(err, "detail", ""))
        finally:
            second._db_lock.release() if second._pid_lock_acquired else None
    finally:
        owner._db_lock.release() if owner._pid_lock_acquired else None
