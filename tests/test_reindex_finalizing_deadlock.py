"""Regression guard for KI 2026-08-28: full reindex hangs in "Finalizing".

Root cause: ``IndexProjectRunner.run()`` holds ``db_manager.begin_write()``
(the global ``_write_lock`` RLock) for the ENTIRE job, including the heavy
LanceDB ``optimize()`` / ``create_index()`` calls in ``_safe_ivf_index()``.
Running those under the lock deadlocks the Finalizing phase (both processes
at 0% CPU, job never completes, ETA grows forever).

These tests pin the fix:
  * optimize/create_index must run with the write lock RELEASED;
  * a hanging create_index must not block the job past a bounded timeout.
"""

import threading
import time
from pathlib import Path

from src.core.indexing.index_project_runner import IndexProjectRunner


class _FakeDBM:
    """Minimal db_manager: begin_write() returns a real threading.Lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reindex = False

    def begin_write(self):
        return self._lock

    def is_reindexing(self):
        return self.reindex


class _LockRecorderTable:
    """Fake LanceDB table that records whether the write lock is held
    at the moment optimize()/create_index() are invoked."""

    def __init__(self, lock):
        self.lock = lock
        self.optimize_called = False
        self.create_called = False
        self.lock_held_at_optimize = None
        self.lock_held_at_create = None

    def count_rows(self):
        return 5000  # force the >1000 branch

    def optimize(self):
        self.optimize_called = True
        self.lock_held_at_optimize = self.lock.locked()
        return None

    def list_indices(self):
        return []

    def create_index(self, *args, **kwargs):
        self.create_called = True
        self.lock_held_at_create = self.lock.locked()


class _SlowTable:
    """Fake table whose create_index() blocks longer than the timeout."""

    def count_rows(self):
        return 5000

    def optimize(self):
        return None

    def list_indices(self):
        return []

    def create_index(self, *args, **kwargs):
        time.sleep(10)  # simulate a hung LanceDB index build


def _make_runner(table, dbm):
    return IndexProjectRunner(
        parse_file_only=lambda *a, **k: None,
        write_file_records=lambda *a, **k: False,
        embedder=None,
        file_guard=None,
        searcher=None,
        table=table,
        path_manager=None,
        project_path=Path("/tmp/mscb_reindex_test"),
        db_manager=dbm,
        db_writer=None,
    )


def test_safe_ivf_index_runs_with_write_lock_released():
    """optimize()/create_index() MUST execute with the global write lock
    FREE (i.e. NOT held by run()'s begin_write()). Reproduces the deadlock
    root cause: if the lock were held here, the Finalizing phase freezes."""
    dbm = _FakeDBM()
    table = _LockRecorderTable(dbm._lock)
    runner = _make_runner(table, dbm)

    # Simulate run() holding the lock for the whole job.
    with dbm.begin_write():
        runner._safe_ivf_index(timeout=5)

    assert table.optimize_called, "optimize() was never called"
    assert table.create_called, "create_index() was never called"
    assert table.lock_held_at_optimize is False, (
        "optimize() ran UNDER the write lock — Finalizing deadlock risk"
    )
    assert table.lock_held_at_create is False, (
        "create_index() ran UNDER the write lock — Finalizing deadlock risk"
    )


def test_safe_ivf_index_create_index_timeout_does_not_hang():
    """A hung create_index() must not block the job past the timeout.
    Verifies the Finalizing phase actually completes even if LanceDB stalls."""
    dbm = _FakeDBM()
    table = _SlowTable()
    runner = _make_runner(table, dbm)

    t0 = time.perf_counter()
    runner._safe_ivf_index(timeout=1)  # create_index sleeps 10s
    dt = time.perf_counter() - t0

    assert dt < 3.0, f"create_index hung the Finalizing phase for {dt:.1f}s"
