"""Cross-process "embedder in use" lease with ref-count (2026-09-25).

Problem: the llama.cpp embedder listens on a FIXED port and is shared by all
MSCodeBase MCP servers (one per Zed/opencode workspace). Each server's
`_watchdog_loop` idle-kills the embedder it spawned after EMBEDDER_IDLE_TIMEOUT
(120s). During a full reindex the long *parse* phase issues no embed calls, so
the embedder looks idle and is killed mid-run — then another workspace's server
grabs the freed port. That is the "servers conflict / it keeps falling" class.

Fix: an indexing process calls :func:`acquire` to register itself as an active
user of the embedder; the idle watchdog checks :func:`is_active` which returns
True only while at least one process holds a non-zero ref-count. Processes call
:func:`release` when done, allowing the embedder to be unloaded when nobody
needs it.

Lease file stores a per-PID ref-count dict so multiple concurrent users are
tracked independently.

Never raises: a recording/best-effort channel.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

__all__ = ["acquire", "release", "is_active", "lease_path", "holder"]

_DEFAULT_MAX_AGE_S = 300.0


def lease_path() -> Path:
    d = Path(tempfile.gettempdir()) / "mscodebase_locks"
    return d / "embedder.lease"


def _load() -> dict:
    """Best-effort load of lease data; returns empty dict on any failure."""
    try:
        p = lease_path()
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001 — corrupt/missing lease = empty
        pass
    return {}


def _save(data: dict) -> None:
    """Best-effort save of lease data."""
    try:
        p = lease_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception:  # noqa: BLE001 — never break indexing over a lease write
        pass


def acquire(pid: Optional[int] = None, reason: str = "") -> None:
    """Register *pid* as an active user of the embedder (increment ref-count).

    Best-effort: never raises.
    """
    if pid is None:
        pid = os.getpid()
    try:
        data = _load()
        pids = data.get("pids", {})
        if not isinstance(pids, dict):
            pids = {}
        key = str(pid)
        entry = pids.get(key, {})
        if not isinstance(entry, dict):
            entry = {}
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["ts"] = time.time()
        entry["reason"] = reason
        pids[key] = entry
        data["pids"] = pids
        data["last_touch"] = time.time()
        _save(data)
    except Exception:  # noqa: BLE001 — never break indexing over a lease write
        pass


def release(pid: Optional[int] = None) -> None:
    """Release one ref-count for *pid* (decrement; remove at zero).

    Best-effort: never raises.
    """
    if pid is None:
        pid = os.getpid()
    try:
        data = _load()
        pids = data.get("pids", {})
        if not isinstance(pids, dict):
            return
        key = str(pid)
        entry = pids.get(key)
        if not isinstance(entry, dict):
            return
        count = int(entry.get("count", 0)) - 1
        if count <= 0:
            pids.pop(key, None)
        else:
            entry["count"] = count
            entry["ts"] = time.time()
            pids[key] = entry
        data["pids"] = pids
        _save(data)
    except Exception:  # noqa: BLE001 — never break indexing over a lease write
        pass


def is_active(max_age_s: float = _DEFAULT_MAX_AGE_S) -> bool:
    """True if some process holds a non-zero ref-count with recent activity.

    A pid is considered active when its ref-count > 0 AND its timestamp is
    within *max_age_s*. This prevents the watchdog from killing the embedder
    while any process still needs it.
    """
    try:
        data = _load()
        pids = data.get("pids", {})
        if not isinstance(pids, dict):
            return False
        now = time.time()
        for _key, entry in pids.items():
            if not isinstance(entry, dict):
                continue
            count = int(entry.get("count", 0))
            ts = float(entry.get("ts", 0))
            if count > 0 and (now - ts) < max_age_s:
                return True
        return False
    except Exception:  # noqa: BLE001 — corrupt/missing lease = not active
        return False


def holder() -> Optional[dict]:
    """Return the lease payload (diagnostics), or None."""
    try:
        return _load() or None
    except Exception:  # noqa: BLE001
        return None


def touch(reason: str = "") -> None:
    """Backward-compatible wrapper: acquire one ref-count for the current PID.

    Deprecated: use :func:`acquire` / :func:`release` directly.
    """
    acquire(reason=reason)
