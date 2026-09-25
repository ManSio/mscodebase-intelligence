"""Guard: run-level single-flight is a lock SEPARATE from the write lock.

Two indexers must never run concurrently (auto-index + manual trigger). Before
2026-09-25 the only mutex was the write RLock held for the whole run; releasing
it (to fix the bulk_write deadlock) let two runs execute at once. The fix splits
the two concerns: begin_run() (run exclusion) vs begin_write() (DB ops).

Run: PYTHONPATH=src python -m pytest tests/test_run_singleflight.py -q
"""
from __future__ import annotations

import threading

import pytest


class _FakeEmbedder:
    def __init__(self, dim: int = 8):
        self.embedding_dim = dim

    def is_ready(self) -> bool:
        return True


@pytest.fixture()
def dbm(tmp_path):
    from src.core.indexing.db_manager import LanceDBManager

    db_path = tmp_path / "db"
    db_path.mkdir()
    m = LanceDBManager(
        db_path=db_path,
        embedder=_FakeEmbedder(),
        project_path=tmp_path,
        embedding_dim=8,
    )
    yield m
    import contextlib

    with contextlib.suppress(Exception):  # noqa: BLE001 — teardown best-effort
        m._db_lock.release()


def test_begin_run_is_not_the_write_lock(dbm):
    assert dbm.begin_run() is not dbm.begin_write()


def test_begin_run_serializes_and_write_lock_stays_free(dbm):
    got = []
    with dbm.begin_run():
        t = threading.Thread(
            target=lambda: (dbm.begin_run().acquire(), got.append(1))
        )
        t.start()
        t.join(0.4)
        assert got == [], "second run acquired the run lock concurrently"

        # The split is what prevents the deadlock: DB writes are NOT blocked by
        # the run lock, so a bounded bulk_write on another thread can proceed.
        assert dbm.begin_write().acquire(blocking=False) is True
        dbm.begin_write().release()

    t.join(2)
    assert got == [1]
