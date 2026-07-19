"""Extension paths - shared between core and MCP layers.

Core intelligence needs to know extension root for runtime context,
but shouldn't import from mcp.* directly.
"""
from pathlib import Path
from typing import Optional

_ext_root: Optional[Path] = None


def get_ext_root() -> Optional[Path]:
    """Get the extension root directory (lazy-loaded)."""
    global _ext_root
    if _ext_root is None:
        try:
            # Try to get from MCP server if available
            from src.mcp.server import _ext_root as mcp_ext_root
            _ext_root = mcp_ext_root
        except ImportError:
            # Fallback: compute from this file's location
            # src/core/utils/extension_paths.py -> go up 4 levels to project root
            # then into extensions/mscodebase-intelligence
            _ext_root = Path(__file__).resolve().parent.parent.parent.parent / "extensions" / "mscodebase-intelligence"
    return _ext_root


def set_ext_root(path: Path) -> None:
    """Explicitly set extension root (used by MCP on startup)."""
    global _ext_root
    _ext_root = path.resolve()