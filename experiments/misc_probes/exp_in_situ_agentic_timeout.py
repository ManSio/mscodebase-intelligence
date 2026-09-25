"""In-situ control #2 (REGRESSION): real `agentic_code_search` sync wrapper.

Calls the ACTUAL method (agentic_search.py) with a hanging
`agentic_code_search_async`, inside a running event loop.

Pre-fix (2026-09-25): returned after ~HANG seconds (the `with ThreadPoolExecutor`
__exit__ joined the hung worker) -> timeout was dead.
Post-fix: must return the default within the timeout, abandoning a daemon worker.
The hardcoded timeout is capped to CAP (via run_bounded) to keep the control short.

Run: PYTHONPATH=src python experiments/misc_probes/exp_in_situ_agentic_timeout.py
"""
from __future__ import annotations

import asyncio
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

from src.core.search.agentic_search import AgenticSearchMixin  # noqa: E402
import src.core.run_bounded as _rb  # noqa: E402

HANG = 5.0
CAP = 1.0
MARGIN = 2.0


class _Probe(AgenticSearchMixin):
    """Bare instance: only what agentic_code_search needs."""


async def _hang_async(*args, **kwargs):
    await asyncio.sleep(HANG)
    return [], {}


def main() -> int:
    inst = _Probe()
    inst.agentic_code_search_async = _hang_async

    _orig_rb = _rb.run_bounded

    def _capped(fn, timeout, *, label="call", default=None):
        return _orig_rb(fn, min(timeout, CAP), label=label, default=default)

    _rb.run_bounded = _capped
    try:
        async def _inner():
            t0 = time.perf_counter()
            res = inst.agentic_code_search("probe query")
            return time.perf_counter() - t0, res

        dt, res = asyncio.run(_inner())
    finally:
        _rb.run_bounded = _orig_rb

    print(f"hang={HANG}s effective_timeout={CAP}s")
    print(f"actual return: {dt:.2f}s  result={res!r}")
    bounded = dt < CAP + MARGIN
    print("in-situ #2 (agentic_code_search): "
          + ("BOUNDED ✅ (abandoned hung worker)" if bounded
             else "NOT BOUNDED ❌ (timeout dead)"))
    return 0 if bounded else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
