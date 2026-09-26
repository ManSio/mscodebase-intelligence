"""Durable reindex failure ledger — append-only JSONL, never raises.

Why (2026-09-25): a full-reindex job was found as a *zombie* — status
"running", but no worker thread and no progress (py-spy: 7 threads, both
executor workers idle). Nothing was recorded, so the cause had to be guessed.
`layer.py` even logged `Exception suppressed at layer.py: ...` without a stack.
This module is the fix: every reindex phase/failure is written to a durable
record so the next incident is *diagnosed*, not guessed.

Design constraints:
- MUST NOT raise, ever (a recording channel cannot break indexing).
- Append-only, one JSON object per line (crash-safe, greppable).
- Path via artifact_paths (single artifact convention, §WISDOM).
"""
from __future__ import annotations

import json
import logging
import os
import time
import traceback
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("MSCodeBase.ReindexLedger")

__all__ = ["record", "ledger_path"]


def ledger_path() -> Optional[Path]:
    """Resolve the ledger file. None if the artifact layer is unavailable."""
    try:
        from src.core.artifact_paths import get_logs_dir

        return Path(get_logs_dir()) / "reindex_ledger.jsonl"
    except Exception:  # noqa: BLE001 — recording must not depend on this
        return None


def record(event: str, *, job_id: str = "", **fields: Any) -> None:
    """Append one ledger line. Swallows every error by design.

    Args:
        event: short machine tag, e.g. "start" | "phase" | "error" | "end" | "zombie".
        job_id: reindex job id.
        **fields: arbitrary JSON-serialisable context (phase, progress, error, tb...).
    """
    try:
        path = ledger_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pid": os.getpid(),
            "event": event,
            "job_id": job_id,
        }
        for k, v in fields.items():
            rec[k] = v
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001 — never propagate
        pass


def exception_fields(exc: BaseException) -> dict:
    """Standard error+short-traceback fields for a ledger record."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return {"error": f"{type(exc).__name__}: {exc}", "traceback": tb[-4000:]}
