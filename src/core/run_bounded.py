"""Bound a NON-CANCELLABLE call by abandoning a daemon worker.

A Python thread cannot be cancelled. ``Future.result(timeout=)`` only stops
waiting, and any explicit join — including a ``with ThreadPoolExecutor`` block's
``__exit__`` (``shutdown(wait=True)``) — then blocks on the hung worker. The only
way a timeout can bound a hung native/sync call is to run it on a daemon thread
and NOT join it (root cause of the 2026-09-25 IVF finalize hang; class audit see
``experiments/misc_probes/exp_timeout_class_audit.py``).

Dependency-free by design: any layer may import it without creating a cycle.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["run_bounded"]


def run_bounded(
    fn: Callable[[], Any],
    timeout: float,
    *,
    label: str = "call",
    default: Any = None,
) -> Any:
    """Run ``fn()`` with a hard time bound that can actually fire.

    Runs ``fn`` on a daemon worker thread and returns when either the worker
    finishes or ``timeout`` elapses — WITHOUT ever joining the worker. If the
    worker is still running at timeout it is ABANDONED (daemon=True keeps
    process exit clean) and ``default`` is returned.

    Args:
        fn: zero-arg callable (wrap args in a lambda).
        timeout: seconds to wait before abandoning the worker.
        label: name used in the abandonment warning / thread name.
        default: value returned when the worker is abandoned.

    Returns:
        ``fn()``'s result, or ``default`` if abandoned. A worker exception is
        re-raised in the caller. ``SystemExit``/``KeyboardInterrupt`` from the
        worker are not propagated (kept to ``Exception``).
    """
    done = threading.Event()
    box: dict = {}

    def _work() -> None:
        try:
            box["result"] = fn()
        except Exception as exc:  # noqa: BLE001 — re-raised in the caller
            box["error"] = exc
        finally:
            done.set()

    th = threading.Thread(target=_work, name=f"bounded-{label}", daemon=True)
    th.start()
    if not done.wait(timeout):
        logger.warning(
            f"{label} exceeded {timeout:.0f}s — ABANDONED (daemon worker; "
            f"non-blocking, non-critical)"
        )
        return default
    if "error" in box:
        raise box["error"]
    return box["result"]
