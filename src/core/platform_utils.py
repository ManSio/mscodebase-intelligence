"""
Централизованное определение платформозависимых путей для Zed IDE.

Единая точка правды для всех macOS/Linux/Windows различных:
  - Директории данных Zed (db, extensions, logs)
  - Директории конфигурации Zed (settings.json)
  - База данных SQLite (workspaces, multi_workspace_state)

Usage:
    # Self-import removed (this file IS platform_utils now)

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
    """Путь к SQLite базе данных Zed (workspaces, multi_workspace_state)."""
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
