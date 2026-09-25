"""Cross-process "embedder in use" lease (2026-09-25).

Problem: the llama.cpp embedder listens on a FIXED port and is shared by all
MSCodeBase MCP servers (one per Zed/opencode workspace). Each server's
`_watchdog_loop` idle-kills the embedder it spawned after EMBEDDER_IDLE_TIMEOUT
(120s). During a full reindex the long *parse* phase issues no embed calls, so
the embedder looks idle and is killed mid-run — then another workspace's server
grabs the freed port. That is the "servers conflict / it keeps falling" class.

Fix: an indexing process creates a short-lived *lease* file refreshed on every
progress tick; the idle watchdog must NOT kill the embedder while any fresh
lease exists (its own reindex or another process's).

Never raises: a recording/best-effort channel.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

__all__ = ["touch", "is_active", "lease_path"]

_DEFAULT_MAX_AGE_S = 300.0


def lease_path() -> Path:
    d = Path(tempfile.gettempdir()) / "mscodebase_locks"
    return d / "embedder.lease"


def touch(reason: str = "") -> None:
    """Mark the shared embedder as in-use right now. Best-effort."""
    try:
        p = lease_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"ts": time.time(), "pid": os.getpid(), "reason": reason}),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 — never break indexing over a lease write
        pass


def is_active(max_age_s: float = _DEFAULT_MAX_AGE_S) -> bool:
    """True if some process recently declared the embedder in use."""
    try:
        p = lease_path()
        if not p.exists():
            return False
        data = json.loads(p.read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0))
        return (time.time() - ts) < max_age_s
    except Exception:  # noqa: BLE001 — corrupt/missing lease = not active
        return False


def holder() -> Optional[dict]:
    """Return the lease payload (diagnostics), or None."""
    try:
        return json.loads(lease_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
