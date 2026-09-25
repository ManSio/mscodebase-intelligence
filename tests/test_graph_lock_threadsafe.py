"""Guard: graph.db lock must serialise SAME-process threads, not fail them.

Regression for 2026-09-25: reindex finalize raised
"Could not acquire cross-process lock for graph.db within 30000ms" because the
named mutex is thread-owned — a second thread of the same process timed out
while another held it. Fix: local RLock per db_path + named mutex.
"""
import tempfile
import threading
import time
from pathlib import Path

from src.core.graph import _cross_process_lock


def test_second_thread_waits_instead_of_failing():
    db = Path(tempfile.mkdtemp(prefix="glock_")) / "graph.db"
    order: list[str] = []
    errors: list[str] = []

    def holder():
        with _cross_process_lock(db, timeout_ms=1000):
            order.append("A-in")
            time.sleep(3.0)          # hold past B's mutex timeout
            order.append("A-out")

    def waiter():
        time.sleep(0.3)              # ensure A holds first
        try:
            with _cross_process_lock(db, timeout_ms=1000):
                order.append("B-in")
        except Exception as exc:     # noqa: BLE001
            errors.append(type(exc).__name__)

    ta = threading.Thread(target=holder)
    tb = threading.Thread(target=waiter)
    ta.start()
    tb.start()
    ta.join(timeout=10)
    tb.join(timeout=10)

    assert not errors, f"second thread failed: {errors}"
    assert "B-in" in order, f"waiter never acquired: {order}"
    # B must acquire only after A released (serialised, not concurrent).
    assert order.index("A-out") < order.index("B-in"), order
