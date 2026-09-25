"""Regression guard: run() excludes concurrent runs via a lock SEPARATE from
the write lock (2026-09-25).

Historical deadlock: run() held the write RLock for the whole run while
`_bounded_link` executed `bulk_write` on a NEW thread which re-acquired the
same RLock -> permanent deadlock (py-spy: "bounded-bulk_write" idle at
db_writer.py:336; job stuck at 52%).

Fix: run() uses `db_manager.begin_run()` (a separate, non-reentrant Lock);
`_bounded_link` no longer releases/touches the write lock. So a bounded DB op
on another thread acquires `_write_lock` freely.

Run: PYTHONPATH=src python -m pytest tests/test_bounded_link_deadlock.py -q
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.core.indexing import index_project_runner as ipr

_ROOT = Path(__file__).resolve().parents[1]


def test_bounded_link_runs_write_locking_fn_without_deadlock(monkeypatch):
    monkeypatch.setattr(ipr, "_LINK_TIMEOUT_SEC", 1.0)

    run_lock = threading.Lock()
    write_lock = threading.RLock()  # what bulk_write actually acquires

    obj = object.__new__(ipr.IndexProjectRunner)

    def fn():
        with write_lock:  # acquired on the bounded worker thread
            return 42

    t0 = time.perf_counter()
    with run_lock:  # run() holds ONLY the run lock, not the write lock
        res = ipr.IndexProjectRunner._bounded_link(obj, fn, "bulk_write", fatal=True)
    dt = time.perf_counter() - t0

    assert res == 42
    assert dt < 0.9, f"took {dt:.2f}s — deadlock behaviour returned"


def test_bounded_link_does_not_touch_write_lock_suspender():
    # Structural contract: the old (broken) remedy must not come back.
    src = (_ROOT / "src/core/indexing/index_project_runner.py").read_text(
        encoding="utf-8"
    )
    start = src.index("def _bounded_link")
    end = src.index("\n    def ", start + 1)
    body = src[start:end]
    assert "with self._suspend_write_lock" not in body
    assert "begin_run(" in src


def test_suspend_write_lock_yields_when_db_manager_missing():
    # _safe_ivf_index still uses it; must be harmless on a bare object.
    obj = object.__new__(ipr.IndexProjectRunner)
    with obj._suspend_write_lock():
        pass


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
