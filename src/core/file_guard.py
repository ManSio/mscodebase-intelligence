"""
Guardrails для файловой системы - защита от бинарников, мусора и .gitignore.
"""

import logging
import os
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)


class FileGuard:
    """Многоуровневая фильтрация файлов перед индексацией."""

    # Жесткий черный список директорий
    SKIP_DIRS = {
        ".git",
        "node_modules",
        "venv",
        ".venv",
        "__pycache__",
        "dist",
        "build",
        "target",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "htmlcov",
        ".coverage",
        ".codebase_index",
        ".codebase_models",
        ".zed",
        ".idea",
        ".vscode",
        "out",
    }

    # Белый список расширений (Всеядность языков)
    SUPPORTED_EXTENSIONS = {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".rs",
        ".go",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".java",
        ".cs",
        ".php",
        ".rb",
        ".swift",
        ".kt",
        ".scala",
        ".r",
        ".m",
        ".mm",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".html",
        ".xml",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".md",
        ".sql",
        ".sh",
        ".bash",
    }

    # Лимит размера файла (1 МБ)
    MAX_FILE_SIZE_BYTES = 1024 * 1024

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self._gitignore_spec = None
        self._load_gitignore()

    def _load_gitignore(self):
        """Загружает правила из .gitignore."""
        gitignore_path = self.project_path / ".gitignore"
        if gitignore_path.exists():
            try:
                import pathspec  # type: ignore[import-not-found]

                with open(gitignore_path, "r", encoding="utf-8") as f:
                    self._gitignore_spec = pathspec.PathSpec.from_lines(  # type: ignore[import-untyped]
                        "gitwildmatch", f
                    )
                logger.info(f"✅ Загружен .gitignore: {gitignore_path}")
            except ImportError:
                logger.warning(
                    "Модуль 'pathspec' не установлен, .gitignore игнорируется."
                )
            except Exception as e:
                logger.warning(f"Не удалось загрузить .gitignore: {e}")

    def should_skip_dir(self, dir_name: str) -> bool:
        """Проверяет, нужно ли пропускать директорию при обходе."""
        return dir_name in self.SKIP_DIRS

    def should_skip_file(self, file_path: Path) -> bool:
        """Проверяет, нужно ли пропускать файл."""
        return not self.is_safe_to_index(file_path)

    def is_safe_to_index(self, file_path: Path) -> bool:
        """Проверяет, безопасен ли файл для индексации. Выполняется от быстрых проверок к медленным."""

        # 1. БЫСТРЫЕ ПРОВЕРКИ СТРОК (Без обращений к диску)

        # Проверка расширения
        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            return False

        # Простая эвристика минифицированных файлов по имени
        if ".min." in file_path.name.lower():
            return False

        # Проверка директорий (если хоть одна часть пути в черном списке - игнорим)
        if any(part in self.SKIP_DIRS for part in file_path.parts):
            return False

        # Проверка .gitignore (Требует POSIX путей)
        if self._gitignore_spec:
            try:
                rel_path = str(file_path.relative_to(self.project_path))
                rel_path_posix = rel_path.replace(os.sep, "/")
                if self._gitignore_spec.match_file(rel_path_posix):
                    return False
            except ValueError:
                # Если файл не является частью проекта
                pass

        # 2. МЕДЛЕННЫЕ ПРОВЕРКИ (I/O Файловой системы)

        # Проверка размера файла (Защита от OOM при чтении)
        try:
            if file_path.stat().st_size > self.MAX_FILE_SIZE_BYTES:
                logger.debug(
                    f"Пропускаю большой файл (>{self.MAX_FILE_SIZE_BYTES} bytes): {file_path}"
                )
                return False
        except (FileNotFoundError, OSError):
            return False

        # Проверка контента на бинарность и минификацию
        if self._is_binary_or_minified(file_path):
            return False

        return True

    def _is_binary_or_minified(self, file_path: Path) -> bool:
        """Настоящая проверка файла на бинарность (как в Git) и скрытую минификацию."""
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(1024)

                if not chunk:
                    return False  # Пустой файл безопасен

                # 1. Проверка на Null-байт (100% гарантия бинарника)
                if b"\x00" in chunk:
                    return True

                # 2. Эвристика на жесткую минификацию
                # Если это текст, но в первых 512 символах вообще нет переносов строк
                text_chunk = chunk.decode("utf-8", errors="ignore")
                if len(text_chunk) > 500:
                    lines = text_chunk.splitlines()
                    if lines and len(lines[0]) > 500:
                        logger.debug(
                            f"Отброшен минифицированный/сжатый файл: {file_path}"
                        )
                        return True

            return False
        except Exception as e:
            # Если файл невозможно прочитать (нет прав, заблокирован ОС), лучше его пропустить
            logger.debug(f"Ошибка чтения файла {file_path}: {e}")
            return True

    def should_skip_dir(self, dir_name: str) -> bool:
        """Проверяет, нужно ли пропускать директорию при обходе."""
        return dir_name in self.SKIP_DIRS

    def should_skip_file(self, file_path: Path) -> bool:
        """Проверяет, нужно ли пропускать файл."""
        return not self.is_safe_to_index(file_path)

    @classmethod
    def get_default_extensions(cls) -> Set[str]:
        """Возвращает список поддерживаемых расширений."""
        return cls.SUPPORTED_EXTENSIONS.copy()

    @classmethod
    def get_default_skip_dirs(cls) -> Set[str]:
        """Возвращает список исключаемых директорий."""
        return cls.SKIP_DIRS.copy()
