"""
Утилиты для работы с путями.
"""

import hashlib
import logging
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SafePathManager:
    """
    Менеджер безопасных путей.
    Решает проблемы с не-ASCII символами (кириллицей, иероглифами) и длинными путями.
    """

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self._temp_dir: Optional[Path] = None
        self._lock = threading.Lock()

    def requires_safe_path(self, path_str: str) -> bool:
        """
        Проверяет, требует ли путь создания безопасной копии.
        Срабатывает на любые не-ASCII символы, пробелы и превышение лимита длины.
        """
        # Проверка на не-ASCII символы (кириллица, эмодзи и т.д.)
        if not path_str.isascii():
            return True

        # Проверка на пробелы
        if " " in path_str:
            return True

        # Проверка на длину (с запасом от Windows MAX_PATH 260)
        if len(path_str) > 200:
            return True

        return False

    def get_safe_path(self, original_path: Path) -> Path:
        """
        Возвращает абсолютно безопасный ASCII-путь к файлу.
        Если оригинальный путь проблемный, создает временную копию с уникальным именем.
        """
        path_str = str(original_path.resolve())

        if not self.requires_safe_path(path_str):
            return original_path

        # Потокобезопасное создание временной директории
        with self._lock:
            if self._temp_dir is None:
                self._temp_dir = Path(tempfile.mkdtemp(prefix="zed_idx_safe_"))

        # Генерируем уникальное имя файла на основе хэша полного пути
        # Это исключает коллизии для файлов с одинаковыми именами в разных папках
        path_hash = hashlib.md5(path_str.encode("utf-8")).hexdigest()

        # Сохраняем оригинальное расширение для корректной работы Tree-sitter/парсеров
        safe_name = f"{path_hash}{original_path.suffix}"
        safe_path = self._temp_dir / safe_name

        # Копируем файл только если его еще нет или он устарел
        try:
            # Сравниваем время изменения, если файл уже существует (защита от изменения исходника)
            if (
                not safe_path.exists()
                or safe_path.stat().st_mtime < original_path.stat().st_mtime
            ):
                shutil.copy2(original_path, safe_path)
        except Exception as e:
            logger.warning(f"Не удалось создать безопасную копию {original_path}: {e}")
            return original_path  # Возвращаем оригинал как fallback

        return safe_path

    def cleanup(self):
        """Удаляет временные файлы и очищает директорию."""
        with self._lock:
            if self._temp_dir and self._temp_dir.exists():
                try:
                    shutil.rmtree(self._temp_dir, ignore_errors=True)
                    logger.debug(f"🧹 Временная папка удалена: {self._temp_dir}")
                except Exception as e:
                    logger.warning(
                        f"Ошибка удаления временной папки {self._temp_dir}: {e}"
                    )
                finally:
                    self._temp_dir = None

    def __del__(self):
        """Гарантирует очистку мусора при уничтожении объекта сборщиком."""
        self.cleanup()
