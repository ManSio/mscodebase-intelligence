r"""
Централизованные платформенные примитивы (ОС) + пути данных Zed IDE.

Единая точка правды для всех macOS/Linux/Windows различных:
  - Максимальная длина пути Windows (\\?\ префикс) — `to_win_long_path`
  - Директории данных Zed (db, extensions, logs)
  - Директории конфигурации Zed (settings.json)
  - База данных SQLite (workspaces, multi_workspace_state)

Слои: `to_win_long_path` — примитив ОС, не деталь `WorkspaceSource`: он нужен и
хранилищу БД (LanceDB), и файловому источнику. Поэтому живёт здесь, а не в
`src/sources/local_fs/windows.py` (там остаётся `SafePathManager` — он про
безопасную обработку путей конкретного источника).

Usage:
    from src.core.platform_utils import to_win_long_path
    Path(to_win_long_path(db_path)).mkdir(parents=True, exist_ok=True)

    db_path = get_zed_db_path()
    if db_path.exists():
        ...
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "is_windows",
    "is_macos",
    "is_linux",
    "platform_label",
    "to_win_long_path",
    "get_zed_db_path",
    "get_zed_logs_dir",
    "get_extension_dir",
    "get_zed_config_path",
    "get_zed_settings_dir",
]
# ─── Детекция платформы ───


def is_windows() -> bool:
    """True на Windows."""
    return sys.platform == "win32"


def is_macos() -> bool:
    """True на macOS (Darwin)."""
    return sys.platform == "darwin"


def is_linux() -> bool:
    """True на Linux."""
    return sys.platform == "linux"


def platform_label() -> str:
    """Человекочитаемая метка платформы."""
    if is_windows():
        return "Windows"
    if is_macos():
        return "macOS"
    if is_linux():
        return "Linux"
    return sys.platform


# ─── Примитивы путей ОС ───


def to_win_long_path(path: Path) -> str:
    """Преобразует путь в абсолютную строку, обходящую MAX_PATH на Windows.

    На Windows добавляет префикс ``\\\\?\\`` (260-символьный лимит), на POSIX —
    обычный `resolve()`. Вызов идемпотентен: уже префиксованный путь не
    дублирует префикс.

    Перенесено из `src/sources/local_fs/windows.py` (2026-11-08): это примитив
    ОС, а не деталь конкретного источника — им пользуется и слой БД.
    """
    abs_path = str(path.resolve())
    if os.name == "nt" and not abs_path.startswith("\\\\?\\"):
        return f"\\\\?\\{abs_path}"
    return abs_path


# ─── Базовые директории Zed ───


def _get_zed_data_base() -> Path:
    """Базовая директория данных Zed (db, extensions, logs).

    Windows: %LOCALAPPDATA%/Zed
    macOS:   ~/Library/Application Support/Zed
    Linux:   ~/.local/share/zed
    """
    if is_windows():
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Zed"
    if is_macos():
        return Path.home() / "Library" / "Application Support" / "Zed"
    # Linux
    xdg = os.environ.get("XDG_DATA_HOME", "")
    if xdg:
        return Path(xdg) / "zed"
    return Path.home() / ".local" / "share" / "zed"


def _get_zed_config_base() -> Path:
    """Базовая директория конфигурации Zed (settings.json, keymap.json).

    Windows: %APPDATA%/Zed
    macOS:   ~/Library/Application Support/Zed
    Linux:   ~/.config/zed
    """
    if is_windows():
        return Path(os.environ.get("APPDATA", "")) / "Zed"
    if is_macos():
        return Path.home() / "Library" / "Application Support" / "Zed"
    # Linux
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        return Path(xdg) / "zed"
    return Path.home() / ".config" / "zed"


# ─── Конкретные пути ───


def get_zed_db_path() -> Path:
    """Путь к SQLite базе данных Zed (workspaces, multi_workspace_state).

    ⚠️ ВНИМАНИЕ: Это недокументированная внутренняя БД Zed.
    Схема может измениться в любой версии без предупреждения.
    Используется ТОЛЬКО для диагностики (check_lsp_health.py).
    Не вызывать из production-кода.
    """
    return _get_zed_data_base() / "db" / "0-stable" / "db.sqlite"


def get_zed_logs_dir() -> Path:
    """Путь к директории логов Zed.

    Windows: %LOCALAPPDATA%/Zed/logs
    macOS:   ~/Library/Logs/Zed
    Linux:   ~/.local/share/zed/logs
    """
    if is_windows():
        return _get_zed_data_base() / "logs"
    if is_macos():
        return Path.home() / "Library" / "Logs" / "Zed"
    # Linux
    return _get_zed_data_base() / "logs"


def get_extension_dir(ext_name: str = "mscodebase-intelligence") -> Path:
    """Путь к директории установленного расширения Zed.

    Args:
        ext_name: ID расширения (по умолчанию mscodebase-intelligence)
    """
    return _get_zed_data_base() / "extensions" / ext_name


def get_zed_config_path() -> Path:
    """Путь к settings.json Zed."""
    return _get_zed_config_base() / "settings.json"


def get_zed_settings_dir() -> Path:
    """Путь к директории настроек Zed."""
    return _get_zed_config_base()
