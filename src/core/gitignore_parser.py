"""
Автоматический парсер .gitignore для исключения файлов из индексации.
"""

import logging
import os
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)


def load_gitignore_patterns(project_path: Path) -> Set[str]:
    """Загружает и парсит .gitignore файл, возвращая набор паттернов для исключения.

    Args:
        project_path: Корневая директория проекта

    Returns:
        Набор паттернов .gitignore (POSIX-формат)
    """
    gitignore_path = project_path / ".gitignore"
    patterns = set()

    if not gitignore_path.exists():
        return patterns

    try:
        import pathspec

        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Парсим .gitignore с использованием gitwildmatch
        spec = pathspec.PathSpec.from_lines("gitwildmatch", content.splitlines())

        # Извлекаем паттерны из спецификации
        for pattern in spec.patterns:
            # Преобразуем паттерн в читаемый паттерн
            pattern_str = str(pattern)
            if pattern_str:
                patterns.add(pattern_str)

        logger.info(
            f"✅ Загружено {len(patterns)} паттернов .gitignore из {gitignore_path}"
        )

    except ImportError:
        logger.warning("Модуль 'pathspec' не установлен, .gitignore игнорируется.")
    except Exception as e:
        logger.warning(f"Не удалось загрузить .gitignore: {e}")

    return patterns


def should_exclude_by_gitignore(
    file_path: Path, project_path: Path, gitignore_patterns: Set[str]
) -> bool:
    """Проверяет, должен ли файл быть исключен на основе .gitignore.

    Args:
        file_path: Абсолютный путь к файлу
        project_path: Корневая директория проекта
        gitignore_patterns: Набор паттернов .gitignore

    Returns:
        True, если файл должен быть исключен, False в противном случае
    """
    if not gitignore_patterns:
        return False

    try:
        # Получаем относительный путь к проекту
        rel_path = file_path.relative_to(project_path)
        rel_path_str = str(rel_path)

        # Преобразуем в POSIX путь (с слешами) - КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ
        rel_path_posix = rel_path_str.replace(os.sep, "/")
        logger.debug(f"[GITIGNORE] Checking file: {rel_path_posix}")

        # Проверяем каждый паттерн
        for pattern in gitignore_patterns:
            try:
                import fnmatch

                if fnmatch.fnmatch(rel_path_posix, pattern):
                    logger.debug(
                        f"[GITIGNORE] File {rel_path_posix} excluded by .gitignore pattern: {pattern}"
                    )
                    return True
            except Exception as e:
                logger.debug(f"[GITIGNORE] Pattern matching error for {pattern}: {e}")
                continue

    except ValueError:
        # Файл не является частью проекта
        logger.debug(f"[GITIGNORE] File not in project: {file_path}")
        return False
    except Exception as e:
        logger.error(
            f"[GITIGNORE ERROR] Failed to check .gitignore for {file_path}: {e}"
        )

    return False


def get_gitignore_exclusions(project_path: Path) -> Set[str]:
    """Получает набор путей, исключаемых на основе .gitignore.

    Args:
        project_path: Корневая директория проекта

    Returns:
        Набор путей для исключения (POSIX-формат)
    """
    patterns = load_gitignore_patterns(project_path)

    # Преобразуем паттерны в конкретные пути для более эффективной проверки
    exclusions = set()

    for pattern in patterns:
        # Простая обработка распространенных паттернов .gitignore
        if pattern == "*":
            # Исключает все файлы
            exclusions.add("*")
        elif pattern.endswith("/"):
            # Исключает директорию и всё в ней
            dir_pattern = pattern.rstrip("/") + "/*"
            exclusions.add(dir_pattern)
        elif pattern.startswith("!"):
            # Исключение инверсии - добавляем как исключение из исключений
            pass
        elif "/" in pattern:
            # Паттерн с директорией
            exclusions.add(pattern)
        else:
            # Простой паттерн файла
            exclusions.add(
                "*/" + pattern if pattern and not pattern.startswith("*") else pattern
            )

    return exclusions


def is_file_excluded_by_gitignore(
    file_path: Path, project_path: Path, gitignore_patterns: Set[str]
) -> bool:
    """Проверяет, исключен ли файл на основе .gitignore паттернов.

    Args:
        file_path: Абсолютный путь к файлу
        project_path: Корневая директория проекта
        gitignore_patterns: Набор паттернов .gitignore

    Returns:
        True, если файл исключен, False в противном случае
    """
    if not gitignore_patterns:
        return False

    try:
        rel_path = file_path.relative_to(project_path)
        rel_path_str = str(rel_path)
        rel_path_posix = rel_path_str.replace(os.sep, "/")
        logger.debug(f"[GITIGNORE] Checking file: {rel_path_posix}")

        for pattern in gitignore_patterns:
            try:
                import fnmatch

                if fnmatch.fnmatch(rel_path_posix, pattern):
                    logger.debug(
                        f"[GITIGNORE] File {rel_path_posix} excluded by .gitignore pattern: {pattern}"
                    )
                    return True
            except Exception as e:
                logger.debug(f"[GITIGNORE] Pattern matching error for {pattern}: {e}")
                continue

    except ValueError:
        logger.debug(f"[GITIGNORE] File not in project: {file_path}")
        return False
    except Exception as e:
        logger.error(
            f"[GITIGNORE ERROR] Failed to check .gitignore for {file_path}: {e}"
        )

    return False


def get_gitignore_summary(project_path: Path) -> dict:
    """Возвращает сводку .gitignore для логирования и отладки.

    Args:
        project_path: Корневая директория проекта

    Returns:
        Словарь с информацией о .gitignore
    """
    gitignore_path = project_path / ".gitignore"

    if not gitignore_path.exists():
        return {
            "exists": False,
            "patterns_count": 0,
            "patterns": [],
            "exclusions_count": 0,
        }

    try:
        import pathspec

        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()

        spec = pathspec.PathSpec.from_lines("gitwildmatch", content.splitlines())

        patterns = list(spec.patterns)
        pattern_strings = []

        for pattern in patterns:
            pattern_strings.append(str(pattern))

        return {
            "exists": True,
            "patterns_count": len(pattern_strings),
            "patterns": pattern_strings,
            "exclusions_count": len(
                [p for p in pattern_strings if not p.startswith("!")]
            ),
        }

    except Exception as e:
        logger.warning(f"Ошибка чтения .gitignore для сводки: {e}")
        return {
            "exists": True,
            "patterns_count": 0,
            "patterns": [],
            "exclusions_count": 0,
            "error": str(e),
        }
