"""
Автоматический парсер .gitignore для исключения файлов из индексации.
"""

import logging
import os
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)

# Module-level cache: project_path -> (mtime, patterns)
# Избегаем пере-парсинга .gitignore на каждый файл.
# Это устраняет 1740 GitWildMatchPattern deprecation warnings в тестах
# и ускоряет проверку .gitignore при индексации.
_gitignore_cache: dict = {}


def load_gitignore_patterns(project_path: Path) -> Set[str]:
    """Загружает и парсит .gitignore файл, возвращая набор паттернов для исключения.

    Caches result by project_path + mtime to avoid re-parsing on every file check.
    Uses 'gitignore' format (not deprecated 'gitwildmatch').

    Args:
        project_path: Корневая директория проекта

    Returns:
        Набор паттернов .gitignore (POSIX-формат)
    """
    gitignore_path = project_path / ".gitignore"
    mtime = gitignore_path.stat().st_mtime if gitignore_path.exists() else -1

    # Cache hit
    cached = _gitignore_cache.get(str(project_path))
    if cached is not None and cached[0] == mtime:
        return cached[1]

    patterns: Set[str] = set()

    if gitignore_path.exists():
        try:
            import pathspec

            with open(gitignore_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Используем 'gitignore' вместо 'gitwildmatch' (deprecated)
            spec = pathspec.PathSpec.from_lines("gitignore", content.splitlines())

            for pattern in spec.patterns:
                pattern_str = str(pattern)
                if pattern_str:
                    patterns.add(pattern_str)

            logger.debug(
                f"✅ Загружено {len(patterns)} паттернов .gitignore из {gitignore_path}"
            )

        except ImportError:
            logger.warning("Модуль 'pathspec' не установлен, .gitignore игнорируется.")
        except Exception as e:
            logger.warning(f"Не удалось загрузить .gitignore: {e}")

    _gitignore_cache[str(project_path)] = (mtime, patterns)
    return patterns


def is_file_excluded_by_gitignore(
    file_path: Path, project_path: Path, gitignore_patterns: Set[str]
) -> bool:
    """Проверяет, исключён ли файл по правилам .gitignore.

    Args:
        file_path: Полный путь к файлу
        project_path: Корень проекта
        gitignore_patterns: Набор паттернов из load_gitignore_patterns()

    Returns:
        True если файл должен быть исключён
    """
    if not gitignore_patterns:
        return False

    try:
        rel_path = str(file_path.relative_to(project_path))
        rel_path_posix = rel_path.replace(os.sep, "/")

        for pattern_str in gitignore_patterns:
            if _match_gitignore_pattern(rel_path_posix, pattern_str):
                return True
    except ValueError:
        return False

    return False


def _match_gitignore_pattern(path: str, pattern: str) -> bool:
    """Простая проверка паттерна .gitignore.

    Args:
        path: Относительный путь в POSIX-формате
        pattern: Паттерн .gitignore

    Returns:
        True если путь соответствует паттерну
    """
    # Убираем начальный слеш
    if pattern.startswith("/"):
        pattern = pattern[1:]

    # Убираем концевой слеш (директория)
    is_dir_pattern = pattern.endswith("/")
    if is_dir_pattern:
        pattern = pattern.rstrip("/")

    # Прямое совпадение
    if path == pattern:
        return True

    # Совпадение с /**/ (любая вложенность)
    if "/**/" in pattern:
        parts = pattern.split("/**/")
        left, right = parts[0], parts[1]
        if left and not path.startswith(left):
            return False
        if right and not path.endswith(right):
            return False
        return True

    # Wildcard: * (любая последовательность кроме /)
    if "*" in pattern:
        import fnmatch

        # Если паттерн содержит /, сравниваем полный путь
        if "/" in pattern:
            return fnmatch.fnmatch(path, pattern)
        # Иначе — имя файла
        return fnmatch.fnmatch(path.split("/")[-1], pattern)

    # Паттерн для имени файла (без /) — проверяем конец пути
    if "/" not in pattern:
        return path.endswith(f"/{pattern}") or path == pattern

    # Префикс пути
    if pattern.endswith("/"):
        return path.startswith(pattern) or path.startswith(f"{pattern}/")

    return False
