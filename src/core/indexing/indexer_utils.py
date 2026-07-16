"""IndexerUtils — мелкие утилиты FileManager + MetaInference."""
from __future__ import annotations

from pathlib import Path

__all__ = [
    "calculate_file_hash",
    "escape_file_path_for_lance",
    "infer_module_name",
    "infer_layer",
]
def calculate_file_hash(safe_path: Path) -> str:
    """SHA256 хэш файла для отслеживания изменений."""
    import hashlib
    hasher = hashlib.sha256()
    with open(str(safe_path), "rb") as f:
        hasher.update(f.read(8192))
    return hasher.hexdigest()


def escape_file_path_for_lance(file_path: str) -> str:
    """Экранирует путь для SQL-like where-выражений LanceDB."""
    return file_path.replace("'", "''")


def infer_module_name(file_path: str) -> str:
    """Извлекает имя модуля из file_path (src/core/parser.py → core.parser)."""
    path = file_path.replace("\\", "/")
    if path.endswith("/__init__.py"):
        path = path[: -len("/__init__.py")]
    elif path.endswith(".py"):
        path = path[:-3]
    # Убираем 'src/' префикс если есть
    return path[4:] if path.startswith("src/") else path


def infer_layer(file_path: str) -> str:
    """Определяет архитектурный слой по пути файла."""
    parts = file_path.replace("\\", "/").split("/")
    SPECIAL = {
        "mcp": "mcp",
        "providers": "providers",
        "scripts": "scripts",
        "tests": "tests",
        "experiments": "experiments",
        "core": "core",
        "utils": "utils",
        "docs": "docs",
    }
    for p in parts:
        if p in SPECIAL:
            return SPECIAL[p]
    return "root"
