"""Self-indexing guard utility — shared across base.py, resolve_indexer_for_request, etc.

Класс/функция, определяющая, является ли путь self-indexing (Zed install dir или ext_root).
"""

import os
from pathlib import Path
from typing import Union


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

    # 2. ext_root check (same logic as in server.py)
    try:
        from src.mcp.server import _ext_root
        if path.resolve() == _ext_root.resolve():
            return True
    except (ImportError, Exception):
        pass

    return False


__all__ = ["_is_self_index_path"]