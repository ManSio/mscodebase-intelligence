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

MCP_EXE_NAME = "mscodebase-mcp.exe"

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


def _ensure_hardlink(src: Path, link_name: str) -> Path:
    """Shared NTFS-hardlink helper (os.link, same inode, never raises).

    If ``link_name`` already exists next to ``src`` it is reused as-is.
    On any failure returns ``src`` so callers fall back to plain spawn.
    """
    try:
        if sys.platform != "win32":
            return src
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
        logger.warning(f"_ensure_hardlink failed ({e}); using {src}")
        return src


def ensure_role_hardlink(bin_path: str | Path, role: str) -> Path:
    """Create (once) an NTFS hardlink ``llama-<role>.exe`` → ``bin_path``.

    Uses ``os.link`` (same inode, no 100MB+ copy). If the link already
    exists, it is reused as-is. On any failure (permissions, FS without
    hardlink support) logs and returns the original ``bin_path`` —
    callers must fall back to plain spawn and never crash startup.
    """
    src = Path(bin_path)
    link_name = ROLE_BIN_NAMES.get(role)
    if not link_name:
        return src
    return _ensure_hardlink(src, link_name)


def resolve_llama_role_bin(bin_path: str | Path, role: str) -> str:
    """Resolve the executable path to spawn for a llama role (str)."""
    return str(ensure_role_hardlink(bin_path, role))


def mcp_exe_name(default_name: str = "pythonw.exe") -> str:
    """Return the MCP hardlink file name (``mscodebase-mcp.exe`` on win32).

    Falls back to ``default_name`` off-Windows so POSIX spawns keep
    using the venv interpreter unchanged.
    """
    if sys.platform != "win32":
        return default_name
    return MCP_EXE_NAME


def ensure_mcp_hardlink(pythonw_path: str | Path) -> Path:
    """Create (once) an NTFS hardlink ``mscodebase-mcp.exe`` → ``pythonw``.

    Same pattern as :func:`ensure_role_hardlink` (os.link, same inode,
    no copy). Console-title approach cannot work because the MCP runs
    under windowless ``pythonw.exe`` (no console to title) — the exe
    name is what Task Manager shows. Never raises: on any failure
    returns the original ``pythonw_path`` for plain-spawn fallback.
    """
    return _ensure_hardlink(Path(pythonw_path), MCP_EXE_NAME)


def resolve_mcp_exe(pythonw_path: str | Path) -> str:
    """Resolve the executable path to spawn for the MCP (str).

    Returns the ``mscodebase-mcp.exe`` hardlink when it exists (or can
    be created); otherwise falls back to the given ``pythonw_path`` —
    e.g. when the hardlink is missing and creation failed.
    """
    return str(ensure_mcp_hardlink(pythonw_path))
