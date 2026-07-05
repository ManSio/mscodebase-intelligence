"""
Guardrails для файловой системы - защита от бинарников, мусора и .gitignore.

Все системные директории и артефакты определены в `SystemArtifacts`.
FileGuard использует их как единый источник правды — никаких дублирующихся
списков. Если нужно добавить новую системную директорию или артефакт —
меняйте `system_artifacts.py`, а не этот файл.
"""

import logging
import os
import time
from pathlib import Path
from typing import Set

from src.core.config import get_config
from src.core.system_artifacts import SystemArtifacts

logger = logging.getLogger(__name__)


class FileGuard:
    """Многоуровневая фильтрация файлов перед индексацией.

    Использует SystemArtifacts как единый источник правды для Layer 1-3.
    Добавляет Layer 4 (Embedding Guard) — проверку бинарности, размера, .gitignore.
    """

    # Системные директории берутся из SystemArtifacts (Layer 1: Directory Guard)
    SKIP_DIRS = SystemArtifacts.get_system_dirs()

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
        self._gitignore_patterns = set()

        # Оптимизация: Вытаскиваем конфигурацию один раз при инициализации
        config = get_config()
        self.max_retries = getattr(config.performance, "file_retry_max_attempts", 3)
        self.retry_delay = getattr(config.performance, "file_retry_delay", 0.1)

        # Кешируем SKIP_DIRS в нижнем регистре для регистронезависимой проверки
        self._skip_dirs_lower = {d.lower() for d in self.SKIP_DIRS}

        self._load_gitignore()

    def should_skip_dir(self, dir_name: str) -> bool:
        """Проверяет, нужно ли пропускать директорию при обходе.

        Layer 1: Directory Guard (SystemArtifacts).
        """
        return SystemArtifacts.is_system_dir(dir_name)

    def should_skip_file(self, file_path: Path) -> bool:
        """Проверяет, нужно ли пропускать файл.

        Layer 2-4: Artifact Guard + Feedback Guard + Embedding Guard.
        """
        # Layer 2: если файл в системной директории — сразу skip
        if SystemArtifacts.is_in_system_dir(file_path):
            return True
        # Layer 3: если файл — feedback risk (создан индексатором)
        if SystemArtifacts.is_feedback_risk(file_path):
            return True
        # Layer 4: полная проверка (расширение, бинарность, размер, .gitignore)
        return not self.is_safe_to_index(file_path)

    def _load_gitignore(self):
        """Загружает правила из .gitignore."""
        try:
            from src.core.gitignore_parser import load_gitignore_patterns
            self._gitignore_patterns = load_gitignore_patterns(self.project_path)
        except Exception as e:
            logger.warning(f"Не удалось загрузить .gitignore парсер: {e}. Будет использован базовый Fallback.")
            self._gitignore_patterns = set()

        # Fallback: паттерны из SystemArtifacts (Layer 2-3: Artifact + Feedback Guard).
        # Если .gitignore повреждён, эти паттерны гарантируют, что служебные
        # файлы не создадут feedback loop в RAG.
        #
        # ВАЖНО: не дублируйте список здесь — SystemArtifacts единственный
        # источник правды. Добавляйте новые паттерны в system_artifacts.py.
        artifact_patterns = SystemArtifacts.get_artifact_patterns()
        feedback_patterns = SystemArtifacts.get_feedback_patterns()
        self._gitignore_patterns.update({
            # LanceDB / векторная БД (железобетонно)
            "codebase_chunks.lance",
            "codebase_chunks/**",
            "*.lance",
            "*.lance_versions/**",
            "lancedb_v2",
            "lancedb_v2/**",
            # Артефакты индексации (Artifact Guard)
            *(p for p in artifact_patterns if p != "*.lance"),
            # Feedback loop риск (Feedback Guard)
            *(p for p in feedback_patterns),
            # Symbol index
            "symbol_index",
            "symbol_index/**",
        })
        logger.info(
            f"✅ Загружено {len(self._gitignore_patterns)} паттернов .gitignore: {self.project_path / '.gitignore'}"
        )

    def is_safe_to_index(self, file_path: Path) -> bool:
        """Проверяет, безопасен ли файл для индексации.
        Выполняется от быстрых проверок к медленным с защитой от блокировок Windows.
        """

        # 1. БЫСТРЫЕ ПРОВЕРКИ СТРОК (Без обращения к диску)

        # Проверка расширения
        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            logger.debug(f"[FILEGUARD SKIP] Unsupported extension: {file_path.suffix}")
            return False

        # Простая эвристика минифицированных файлов по имени
        if ".min." in file_path.name.lower():
            logger.debug(f"[FILEGUARD SKIP] Minified file: {file_path.name}")
            return False

        # Проверка системной директории (Layer 1: Directory Guard)
        # if is_in_system_dir — этот вызов уже сделан в should_skip_file,
        # но дублируем здесь для is_safe_to_index при прямом вызове.
        if SystemArtifacts.is_in_system_dir(file_path):
            logger.debug(f"[FILEGUARD SKIP] System directory: {file_path}")
            return False

        # Проверка .gitignore (Требует POSIX путей)
        if self._gitignore_patterns:
            try:
                rel_path = str(file_path.relative_to(self.project_path))
                rel_path_posix = rel_path.replace(os.sep, "/")
                from src.core.gitignore_parser import is_file_excluded_by_gitignore

                if is_file_excluded_by_gitignore(
                    file_path, self.project_path, self._gitignore_patterns
                ):
                    logger.debug(
                        f"[FILEGUARD SKIP] Excluded by .gitignore: {file_path}"
                    )
                    return False
            except ValueError:
                # Если файл не является частью проекта
                logger.debug(f"[FILEGUARD SKIP] File not in project: {file_path}")
                return False

        # 2. МЕДЛЕННЫЕ ПРОВЕРКИ (I/O Файловой системы) с Retry-логикой под Windows
        st_size = 0
        for attempt in range(self.max_retries):
            try:
                # Пытаемся получить информацию о файле
                st_size = file_path.stat().st_size

                # Дополнительная проверка: если размер 0, возможно, файл еще пишется.
                # Даем ему шанс заполниться, если это не пустой файл изначально.
                if st_size == 0 and attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue

                break  # Если всё успешно прочиталось, выходим из цикла ретраев

            except (FileNotFoundError, OSError) as e:
                if attempt == self.max_retries - 1:
                    # Если это была последняя попытка — логируем жесткий пропуск
                    logger.debug(
                        f"[FILEGUARD SKIP] File stat permanent error after {self.max_retries} attempts: {e}"
                    )
                    return False

                # Если поймали PermissionError (WinError 32) — спим и пробуем снова
                if isinstance(e, PermissionError):
                    logger.debug(
                        f"[FILEGUARD RETRY] File locked by OS (PermissionError) (attempt {attempt + 1}/{self.max_retries}). Retrying..."
                    )
                else:
                    logger.debug(
                        f"[FILEGUARD RETRY] File locked by OS (attempt {attempt + 1}/{self.max_retries}). Retrying..."
                    )
                time.sleep(self.retry_delay)

        # Проверка размера файла после успешного получения статов
        if st_size > self.MAX_FILE_SIZE_BYTES:
            logger.debug(
                f"[FILEGUARD SKIP] Large file (>{self.MAX_FILE_SIZE_BYTES} bytes): {file_path}"
            )
            return False

        # Проверка контента на бинарность и минификацию
        if self._is_binary_or_minified(file_path):
            logger.debug(f"[FILEGUARD SKIP] Binary or minified file: {file_path}")
            return False

        logger.debug(f"[FILEGUARD OK] File passed all checks: {file_path}")
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

    @classmethod
    def get_default_extensions(cls) -> Set[str]:
        """Возвращает список поддерживаемых расширений."""
        return cls.SUPPORTED_EXTENSIONS.copy()

    @classmethod
    def get_default_skip_dirs(cls) -> Set[str]:
        """Возвращает список исключаемых директорий."""
        return cls.SKIP_DIRS.copy()
