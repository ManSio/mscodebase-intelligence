"""Canonical relative-path form for the index.

The index stores relative paths; they MUST be one form (POSIX, ``/``). Full
reindex used to emit Windows ``\\`` while hot-reload emitted ``/``, so the same
file became two rows and every incremental pass re-added the alternate form
(~2x bloat, 2026-09-25). Every write/compare path normalises through here.
"""
from __future__ import annotations

__all__ = ["normalize_rel_path"]


def normalize_rel_path(path) -> str:
    """Return the canonical POSIX relative path (backslashes -> slashes)."""
    return str(path).replace("\\", "/")
