from __future__ import annotations

import logging
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("MSCodeBase.Intelligence.Staleness")

STATUS_ACTIVE = "ACTIVE"
STATUS_STALE = "STALE"
STATUS_EXPIRED = "EXPIRED"

DISCRIMINATOR_TIMEOUT = 5


def check_note_staleness(
    note: Dict[str, Any],
    *,
    now: Optional[date] = None,
    project_root: Optional[Path] = None,
) -> str:
    if now is None:
        now = date.today()

    stale_after = note.get("stale_after")
    if stale_after:
        try:
            stale_date = datetime.strptime(stale_after, "%Y-%m-%d").date()
            if now > stale_date:
                return STATUS_STALE
        except (ValueError, TypeError):
            logger.warning(
                "Invalid stale_after format for node %s: %s",
                note.get("node_id", "?"),
                stale_after,
            )

    discriminator = note.get("discriminator")
    if discriminator:
        exit_code = _run_discriminator(discriminator, project_root=project_root)
        if exit_code != 0:
            return STATUS_EXPIRED

    return STATUS_ACTIVE


def _run_discriminator(command: str, *, project_root: Optional[Path] = None) -> int:
    cwd = str(project_root) if project_root else None
    kwargs: Dict[str, Any] = {
        "capture_output": True,
        "timeout": DISCRIMINATOR_TIMEOUT,
        "shell": True,
    }
    if cwd:
        kwargs["cwd"] = cwd
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        result = subprocess.run(command, **kwargs)
        return result.returncode
    except subprocess.TimeoutExpired:
        logger.warning("Discriminator timed out after %ss: %s", DISCRIMINATOR_TIMEOUT, command)
        return -1
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        logger.warning("Discriminator failed to run: %s — %s", command, e)
        return -1
