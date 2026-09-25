"""Guard: every native link in the indexer chain is bounded (2026-09-25).

Failure injection: a hanging link must NOT freeze the phase. Non-fatal links are
skipped; fatal links (embed / DB write) raise a resume-safe error.
"""
import time

import pytest

import src.core.indexing.index_project_runner as ipr


def _runner() -> ipr.IndexProjectRunner:
    return object.__new__(ipr.IndexProjectRunner)  # bypass __init__


def test_bounded_link_returns_value():
    r = _runner()
    assert r._bounded_link(lambda: 42, "ok") == 42


def test_bounded_link_non_fatal_skips_within_timeout(monkeypatch):
    monkeypatch.setattr(ipr, "_LINK_TIMEOUT_SEC", 1.0)
    r = _runner()
    t0 = time.perf_counter()
    out = r._bounded_link(lambda: time.sleep(10), "prune", default=0)
    dt = time.perf_counter() - t0
    assert out == 0
    assert dt < 3.0, f"non-fatal link hung for {dt:.1f}s"


def test_bounded_link_fatal_raises_within_timeout(monkeypatch):
    monkeypatch.setattr(ipr, "_LINK_TIMEOUT_SEC", 1.0)
    r = _runner()
    t0 = time.perf_counter()
    with pytest.raises(RuntimeError, match="native stall"):
        r._bounded_link(lambda: time.sleep(10), "embed_batch", fatal=True)
    assert time.perf_counter() - t0 < 3.0


def test_bounded_link_propagates_normal_exception():
    r = _runner()

    def _boom():
        raise ValueError("real error")

    with pytest.raises(ValueError, match="real error"):
        r._bounded_link(_boom, "x")
