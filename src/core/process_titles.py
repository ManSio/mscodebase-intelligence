"""Process naming: MCP console title + llama role hardlinks (Windows).

Minimal, Windows-guarded helpers so Task Manager shows
``mscodebase-mcp:<name>-<hash8>`` and ``llama-embed.exe`` /
``llama-rerank.exe`` instead of bare ``python.exe`` /
``llama-server.exe``.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("MSCodebase.process_titles")

MCP_TITLE_PREFIX = "mscodebase-mcp"

ROLE_BIN_NAMES = {
    "embed": "llama-embed.exe",
    "rerank": "llama-rerank.exe",
}


def build_mcp_title(project_path: str | Path | None = None) -> str:
    """Build ``mscodebase-mcp:<name>-<hash8>`` title string.

    Reuses the canonical :func:`src.core.artifact_paths.project_hash`
    helper — no invented hashing.
    """
    name = "unknown"
    hash8 = "unknown"
    try:
        if project_path:
            p = Path(project_path)
            name = p.name or "unknown"
            from src.core.artifact_paths import project_hash

            hash8 = project_hash(p)
    except Exception:  # noqa: BLE001
        pass
    return f"{MCP_TITLE_PREFIX}:{name}-{hash8}"


def set_console_title(title: str) -> bool:
    """Set Windows console title (win32 only, never raises).

    Returns True if the title was set, False otherwise (non-Windows
    or any error). Guards the ``ctypes.windll`` access which does not
    exist outside Windows.
    """
    try:
        if sys.platform != "win32":
            return False
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug(f"set_console_title failed: {e}")
        return False


def apply_mcp_process_title(project_path: str | Path | None = None) -> str:
    """Build + apply (+ log) the MCP console title. Never raises."""
    title = build_mcp_title(project_path)
    ok = set_console_title(title)
    try:
        logger.info(f"Process title: {title} (applied={ok})")
    except Exception:  # noqa: BLE001
        pass
    return title


def role_bin_name(role: str, default_name: str = "llama-server.exe") -> str:
    """Map a llama role (``embed``/``rerank``) to its hardlink file name."""
    if sys.platform != "win32":
        return default_name
    return ROLE_BIN_NAMES.get(role, default_name)


def ensure_role_hardlink(bin_path: str | Path, role: str) -> Path:
    """Create (once) an NTFS hardlink ``llama-<role>.exe`` → ``bin_path``.

    Uses ``os.link`` (same inode, no 100MB+ copy). If the link already
    exists, it is reused as-is. On any failure (permissions, FS without
    hardlink support) logs and returns the original ``bin_path`` —
    callers must fall back to plain spawn and never crash startup.
    """
    src = Path(bin_path)
    try:
        if sys.platform != "win32":
            return src
        link_name = ROLE_BIN_NAMES.get(role)
        if not link_name:
            return src
        link = src.parent / link_name
        if link.exists():
            return link
        try:
            os.link(str(src), str(link))
            logger.info(f"Hardlink created: {link} -> {src}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Hardlink {link} failed ({e}); using {src}")
            return src
        return link
    except Exception as e:  # noqa: BLE001
        logger.warning(f"ensure_role_hardlink failed ({e}); using {src}")
        return src


def resolve_llama_role_bin(bin_path: str | Path, role: str) -> str:
    """Resolve the executable path to spawn for a llama role (str)."""
    return str(ensure_role_hardlink(bin_path, role))
