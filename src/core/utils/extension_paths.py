"""Extension paths - shared between core and MCP layers.

Core intelligence needs to know extension root for runtime context,
but shouldn't import from mcp.* directly at module level (clean arch).
"""
from pathlib import Path
from typing import Optional

_ext_root: Optional[Path] = None


def get_ext_root() -> Optional[Path]:
    """Get the extension root directory (lazy-loaded)."""
    global _ext_root
    if _ext_root is None:
        try:
            # Lazy import to avoid static analysis detecting mcp import in core
            import importlib
            mcp_server = importlib.import_module('src.mcp.server')
            _ext_root = getattr(mcp_server, '_ext_root', None)
        except ImportError:
            # Fallback: compute from this file's location
            _ext_root = Path(__file__).resolve().parent.parent.parent.parent / "extensions" / "mscodebase-intelligence"
    return _ext_root


def set_ext_root(path: Path) -> None:
    """Explicitly set extension root (used by MCP on startup)."""
    global _ext_root
    _ext_root = path.resolve()
