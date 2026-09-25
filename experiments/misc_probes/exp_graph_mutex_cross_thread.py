"""Experiment: graph.db cross-process mutex is not reentrant across threads.

Reproduces the reindex finalize failure
  "Could not acquire cross-process lock for graph.db within 30000ms"
by holding the named mutex on one thread and trying to acquire it on another.

HYPOTHESIS: with the same process, a second ACQUIRE (different thread) blocks
and returns False once timeout_ms elapses. => any concurrent graph operation
(live search / symbol build) held longer than the timeout fails the other one.

Run: PYTHONPATH=src python experiments/misc_probes/exp_graph_mutex_cross_thread.py
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.graph import _CrossProcessMutex  # noqa: E402

DB = Path(tempfile.mkdtemp(prefix="graphmutex_")) / "graph.db"
HOLD = 3.0
TMO_MS = 800


def main() -> int:
    if sys.platform != "win32":
        print("non-win32: mutex is a no-op; skipped")
        return 0

    a = _CrossProcessMutex(DB)
    assert a.acquire(1000), "first acquire should succeed"

    result = {}

    def second():
        b = _CrossProcessMutex(DB)
        t0 = time.perf_counter()
        ok = b.acquire(TMO_MS)     # different thread, same named mutex
        result["ok"] = ok
        result["dt"] = time.perf_counter() - t0
        if ok:
            b.release()

    th = threading.Thread(target=second)
    th.start()
    time.sleep(HOLD)               # hold the mutex past B's timeout
    a.release()
    th.join(timeout=5)

    print(f"hold={HOLD}s  second acquire timeout={TMO_MS}ms")
    print(f"second thread acquired: {result.get('ok')} after {result.get('dt',0):.2f}s")
    blocked = (result.get("ok") is False) and (result.get("dt", 0) >= TMO_MS / 1000 - 0.2)
    print("cross-thread contention: " + ("CONFIRMED" if blocked else "REFUTED"))
    return 0 if blocked else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
