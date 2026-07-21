"""Self-indexing guard utility — shared across core and MCP.

Core intelligence needs to check self-indexing paths, but shouldn't
import from mcp.* at module level (clean arch).
"""

import os
from pathlib import Path
from typing import Union


def is_zed_install_dir(path: Path) -> bool:
    """Check if path is a Zed installation directory."""
    markers = ["Zed.exe", "zed.exe", "Zed.app"]
    return any((path / m).exists() for m in markers)


def _is_self_index_path(path: Union[str, Path, None]) -> bool:
    """Проверяет, является ли путь self-indexing (Zed install или ext_root).

    Self-indexing targets:
    1. Zed install dir (см. is_zed_install_dir)
    2. _ext_root (директория самого расширения)
    3. None (неопределённый project_path)

    Override: env var MSCODEBASE_ALLOW_SELF_INDEX=1 разрешает индексировать
    даже ext_root/Zed install (для разработки самого расширения).
    """
    # Allow override for dev
    if os.environ.get("MSCODEBASE_ALLOW_SELF_INDEX", "").strip() in ("1", "true", "yes"):
        return False

    if path is None:
        return True
    path = Path(path)

    # 1. Zed install dir check
    try:
        from src.core.lsp_project_bridge import is_zed_install_dir
        if is_zed_install_dir(path):
            return True
    except ImportError:
        pass

    # 2. ext_root check (lazy import via importlib)
    try:
        import importlib
        mcp_server = importlib.import_module('src.mcp.server')
        ext_root = getattr(mcp_server, '_ext_root', None)
        if ext_root is not None and path.resolve() == ext_root.resolve():
            return True
    except (ImportError, Exception):
        pass

    # 3. Fallback check
    if is_zed_install_dir(path):
        return True

    return False


__all__ = ["_is_self_index_path"]
