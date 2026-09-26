"""Negative control for the IVF finalize timeout guard (in-code, in-situ).

Injects a `table.optimize` that blocks longer than the timeout and asserts that
`IndexProjectRunner._safe_ivf_index` returns within timeout + margin.

On the CURRENT code this MUST FAIL (the guard cannot fire): the `finally:
shutdown(wait=True)` joins the blocked worker. After the fix it MUST PASS.
This is the regression test that proves the guard can fail.

Run: PYTHONPATH=src python experiments/misc_probes/exp_ivf_guard_negative_control.py
"""
from __future__ import annotations

import contextlib
import sys
import time
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TIMEOUT = 1.0
BLOCK = 5.0
MARGIN = 2.0   # accept up to timeout + margin

try:
    from src.core.indexing.index_project_runner import IndexProjectRunner
except Exception as exc:  # pragma: no cover
    import traceback
    traceback.print_exc()
    print(f"IMPORT FAILED: {exc}")
    sys.exit(2)


class BlockingTable:
    """Stands in for the LanceDB table whose native optimize() hangs."""

    def optimize(self, *a, **k):  # the "hung" native call
        time.sleep(BLOCK)
        return None

    def list_indices(self):
        return []

    def create_index(self, *a, **k):
        return None

    def count_rows(self):
        return 0


def main() -> int:
    runner = object.__new__(IndexProjectRunner)   # bypass __init__
    runner.table = BlockingTable()
    runner._suspend_write_lock = lambda: contextlib.nullcontext()

    t0 = time.perf_counter()
    runner._safe_ivf_index(timeout=TIMEOUT)
    elapsed = time.perf_counter() - t0

    print(f"configured timeout : {TIMEOUT:.1f}s")
    print(f"simulated hang     : {BLOCK:.1f}s")
    print(f"actual return      : {elapsed:.2f}s")
    limit = TIMEOUT + MARGIN
    ok = elapsed < limit
    print(f"guard fired (< {limit:.1f}s): {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("=> CONFIRMED BUG: timeout guard cannot bound the hung call "
              "(shutdown(wait=True) joins it).")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
