"""Guard: the indexer must say *what* it is blocked on (2026-11-08).

Research pattern P-B ("still digging" == "hung" without a heartbeat): every
native link of the chain is bounded (300 s), but bounded-by-silence still looks
like a hang. `wait_state` records the current wait and `get_status()` exposes it
as `wait_reason`, so an agent can distinguish "prune is slow" from "stuck".

Scope is deliberately partial and documented in the module: native links are
reported, the write lock is not (it is held for the whole run by design).
"""
from __future__ import annotations

from src.core.indexing.index_project_runner import IndexProjectRunner
from src.core.indexing.index_status import IndexStatusReporter
from src.core.indexing.wait_state import clear_wait, set_wait, snapshot


class TestWaitState:
    def test_idle_is_none(self):
        clear_wait()
        assert snapshot() is None

    def test_set_and_clear(self):
        set_wait("native:prune", 300)
        frame = snapshot()
        assert frame["reason"] == "native:prune"
        assert frame["timeout_s"] == 300
        assert frame["elapsed_ms"] >= 0
        clear_wait()
        assert snapshot() is None

    def test_nested_frames_restore_the_outer_one(self):
        set_wait("native:parse:a.py", 60)
        set_wait("native:embed_batch", 300)
        assert snapshot()["reason"] == "native:embed_batch"
        clear_wait()
        assert snapshot()["reason"] == "native:parse:a.py"
        clear_wait()
        assert snapshot() is None

    def test_clear_on_empty_never_raises(self):
        clear_wait()
        clear_wait()
        assert snapshot() is None


class TestBoundedLinkReportsWait:
    def _runner(self):
        # _bounded_link uses no instance state; skip __init__ (it opens LanceDB)
        return object.__new__(IndexProjectRunner)

    def test_wait_is_visible_during_the_call_and_gone_after(self):
        seen = {}

        def slow_link():
            seen.update(snapshot() or {})
            return 7

        result = IndexProjectRunner._bounded_link(self._runner(), slow_link, "prune")

        assert result == 7
        assert seen["reason"] == "native:prune"
        assert seen["timeout_s"] > 0
        assert snapshot() is None, "wait must be cleared even on success"

    def test_wait_is_cleared_when_the_link_raises(self):
        def boom():
            raise ValueError("native failure")

        try:
            IndexProjectRunner._bounded_link(self._runner(), boom, "bulk_write")
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("ValueError should propagate")
        assert snapshot() is None, "wait must be cleared on the error path too"


class TestStatusExposesWait:
    def _reporter(self, tmp_path, reindex_check=None):
        return IndexStatusReporter(
            table=None,
            project_path=tmp_path,
            file_guard=None,
            watchdog_callback=None,
            reindex_check=reindex_check,
        )

    def test_idle_status_has_explicit_none(self, tmp_path):
        clear_wait()
        status = self._reporter(tmp_path).get_status()
        assert "wait_reason" in status
        assert status["wait_reason"] is None

    def test_active_wait_is_exposed(self, tmp_path):
        set_wait("native:bm25_reindex", 300)
        try:
            status = self._reporter(tmp_path).get_status()
            assert status["wait_reason"]["reason"] == "native:bm25_reindex"
        finally:
            clear_wait()

    def test_reindex_fast_fail_branch_also_exposes_it(self, tmp_path):
        set_wait("native:save_symbol_index", 300)
        try:
            status = self._reporter(tmp_path, reindex_check=lambda: True).get_status()
            assert status["status"] == "reindexing"
            assert status["wait_reason"]["reason"] == "native:save_symbol_index"
        finally:
            clear_wait()
