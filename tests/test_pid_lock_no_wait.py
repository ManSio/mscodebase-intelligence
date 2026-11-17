"""Guard: старт не ждёт живого держателя (wait=False) — ревью/замер 2026-11-16.

Замер: `initialize` 10–15 с вместо 2.5 с, если chunks.db проекта держит живой
MCP-процесс: `Indexer.__init__` → `DatabaseLock.acquire()` ждал освобождения
полный wait_timeout (8 с), хотя read-only режим уже поддержан.
"""
from __future__ import annotations

import time

import pytest

from src.core.indexing.database_lock import DatabaseLock


def test_wait_false_fails_fast_for_a_live_holder(tmp_path):
    lock_path = tmp_path / "db" / ".write_lock"
    lock1 = DatabaseLock(lock_path, wait_timeout=5.0, poll_interval=0.05)
    lock1.acquire()
    try:
        lock2 = DatabaseLock(lock_path, wait_timeout=5.0, poll_interval=0.05)
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="wait=False"):
            lock2.acquire(wait=False)
        elapsed = time.monotonic() - started

        assert elapsed < 0.5, f"ждали {elapsed:.2f} с вместо мгновенного отказа"
        assert lock1.is_held() is True, "чужой lock не должен сниматься"
    finally:
        lock1.release()


def test_wait_false_still_steals_a_dead_holder(tmp_path):
    """Мёртвый держатель перехватывается и в режиме без ожидания."""
    import json
    import os

    lock_path = tmp_path / "db" / ".write_lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"pid": 999_999_999, "started": 0, "role": "worker"}),
        encoding="utf-8",
    )

    lock = DatabaseLock(lock_path, wait_timeout=0.2)
    lock.acquire(wait=False)
    try:
        assert lock.is_held() is True
        assert json.loads(lock_path.read_text(encoding="utf-8"))["pid"] == os.getpid()
    finally:
        lock.release()
