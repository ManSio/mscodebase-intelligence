"""
Утилиты для работы с путями.
Обеспечивает полную защиту от специфики Windows (длинные пути, зарезервированные имена устройств).
"""

import hashlib
import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Полный список зарезервированных имен устройств Windows (регистронезависимый)
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
}


def to_win_long_path(path_str: str) -> str:
    """
    Преобразует путь в формат длинных путей Windows (\\\\?\\), если запущено на Windows.
    Это предотвращает падения на лимите в 260 символов (MAX_PATH).
    """
    if os.name != "nt":
        return path_str

    abs_path = os.path.abspath(path_str)
    if abs_path.startswith("\\\\?\\"):
        return abs_path

    if abs_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abs_path[2:]
    return "\\\\?\\" + abs_path


def is_windows_reserved_path(path: Path) -> bool:
    """
    Проверяет, содержит ли путь зарезервированные системные имена Windows (например, NUL, CON).
    """
    try:
        stem = path.stem.lower()
        if stem in WINDOWS_RESERVED_NAMES:
            return True

        for part in path.parts:
            if part.lower() in WINDOWS_RESERVED_NAMES:
                return True
    except Exception:
        pass
    return False


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
        Срабатывает на любые не-ASCII символы, пробелы, превышение лимита длины или системные имена Windows.
        """
        original_path = Path(path_str)

        if is_windows_reserved_path(original_path):
            return True

        if not path_str.isascii():
            return True

        if " " in path_str:
            return True

        if len(path_str) > 200:
            return True

        return False

    def get_safe_path(self, original_path_str: str) -> Path:
        """
        Возвращает безопасный путь к файлу.
        Если путь проблемный — создает его хэшированную копию во временной директории.
        """
        if not self.requires_safe_path(original_path_str):
            return Path(original_path_str)

        original_path = Path(original_path_str)

        # Если это системное зарезервированное устройство Windows, физически прочитать его нельзя
        if is_windows_reserved_path(original_path):
            logger.warning(
                f"⚠️ Обнаружено системное устройство Windows в путях: {original_path_str}. Возвращаем fallback."
            )
            return original_path

        with self._lock:
            if self._temp_dir is None:
                self._temp_dir = Path(tempfile.mkdtemp(prefix="mscodebase_safe_paths_"))
                logger.debug(f"📁 Создана папка для безопасных путей: {self._temp_dir}")

        # Хэшируем исходный абсолютный путь, чтобы избежать коллизий имен
        path_hash = hashlib.md5(
            original_path_str.encode("utf-8", errors="ignore")
        ).hexdigest()
        safe_name = f"{path_hash}{original_path.suffix}"
        safe_path = self._temp_dir / safe_name

        try:
            # Защита длинных путей при операциях копирования
            win_src = to_win_long_path(str(original_path))
            win_dst = to_win_long_path(str(safe_path))

            if (
                not safe_path.exists()
                or safe_path.stat().st_mtime < original_path.stat().st_mtime
            ):
                shutil.copy2(win_src, win_dst)
        except Exception as e:
            logger.warning(
                f"❌ Не удалось создать безопасную копию {original_path_str}: {e}"
            )
            return original_path

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
        self.cleanup()
