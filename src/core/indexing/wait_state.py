"""What the indexer is blocked on right now (process-local, self-resetting).

Motivation (research 2026-09-25, pattern P-B): while a bounded native link runs,
CPU is idle and the job is "running", but nothing says *what* it waits on. The
job used to look hung; now the link is bounded to `MSCODEBASE_LINK_TIMEOUT_SEC`,
and this module makes the wait observable, so an agent can tell
"prune takes 40 s" from "the process is stuck".

Contract:
  * `set_wait(reason, timeout_s)` — push a wait frame (stack, so nested calls
    restore the outer frame);
  * `clear_wait()` — pop the frame; safe to call when empty;
  * `snapshot()` — `None` when nothing is being waited on, otherwise
    `{"reason", "elapsed_ms", "timeout_s"}`.

Scope and honesty:
  * reported: bounded native links, labelled like `native:prune`,
    `native:embed_batch`, `native:ivf-create_index`, `native:parse:<file>`;
  * NOT reported: the write lock. `run()` holds it for the whole reindex by
    design, so "waiting on lock:write" would be true almost always and would
    mislead more than it explains; real cross-process contention already
    surfaces as the read-only mode message in `LanceDBManager.begin_write`.

Concurrency: frames live in one process-wide stack behind a lock. The indexer
serialises runs (`begin_run`), so in practice a single writer exists; if that
ever changes, the stack order is the only thing at risk (never correctness of
the index).
"""
from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["set_wait", "clear_wait", "snapshot"]

_LOCK = threading.Lock()
_FRAMES: list[dict] = []


def set_wait(reason: str, timeout_s: Optional[float] = None) -> None:
    """Record that we are about to block on `reason`."""
    with _LOCK:
        _FRAMES.append({"reason": reason, "started": time.monotonic(), "timeout_s": timeout_s})


def clear_wait() -> None:
    """Pop the current frame. Safe when empty (never raises)."""
    with _LOCK:
        if _FRAMES:
            _FRAMES.pop()


def snapshot() -> Optional[dict]:
    """Current wait frame as a plain dict, or None when nothing waits."""
    with _LOCK:
        if not _FRAMES:
            return None
        frame = _FRAMES[-1]
        return {
            "reason": frame["reason"],
            "elapsed_ms": int((time.monotonic() - frame["started"]) * 1000),
            "timeout_s": frame["timeout_s"],
        }
