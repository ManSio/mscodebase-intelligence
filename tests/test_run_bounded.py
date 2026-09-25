"""Guard: run_bounded must actually bound a hung (non-cancellable) call.

Regression for the timeout class (2026-09-25): a timeout that ends in a join
cannot fire. run_bounded never joins the worker — it abandons a daemon thread.
"""
import time

import pytest

from src.core.run_bounded import run_bounded


def test_finishes_returns_value():
    assert run_bounded(lambda: 42, timeout=5) == 42


def test_exception_is_reraised():
    def _boom():
        raise ValueError("inner")

    with pytest.raises(ValueError, match="inner"):
        run_bounded(_boom, timeout=5)


def test_hung_call_is_abandoned_within_timeout():
    t0 = time.perf_counter()
    out = run_bounded(lambda: time.sleep(10), timeout=1.0, default="ABANDONED")
    dt = time.perf_counter() - t0
    assert out == "ABANDONED"
    assert dt < 3.0, f"run_bounded did not bound the hung call ({dt:.1f}s)"


def test_hang_does_not_join_a_non_daemon_worker():
    """The whole class: caller returns even though the worker keeps running."""
    t0 = time.perf_counter()
    run_bounded(lambda: time.sleep(30), timeout=1.0)
    assert time.perf_counter() - t0 < 3.0


def test_default_returned_on_abandon_is_type_appropriate():
    assert run_bounded(lambda: time.sleep(5), timeout=1.0, default=([], {})) == ([], {})
