"""
MSCodebase Intelligence — Безопасное управление путями файловой системы
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


def to_win_long_path(path: Path) -> str:
    """
    Преобразует путь в абсолютную строку.
    На Windows добавляет префикс \\\\?\\ для обхода лимита MAX_PATH (260 символов).
    """
    abs_path = str(path.resolve())
    if os.name == "nt" and not abs_path.startswith("\\\\?\\"):
        return f"\\\\?\\{abs_path}"
    return abs_path


class SafePathManager:
    """Менеджер безопасных путей для изоляции не-ASCII символов и длинных путей."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self._temp_dir: Optional[Path] = None
        self._lock = threading.Lock()

    def requires_safe_path(self, path_str: str) -> bool:
        if not path_str.isascii() or " " in path_str or len(path_str) > 200:
            return True
        return False

    def get_safe_path(self, original_path: Path) -> Path:
        if not original_path.exists():
            return original_path
        if not self.requires_safe_path(str(original_path)):
            return original_path

        with self._lock:
            if not self._temp_dir:
                self._temp_dir = Path(tempfile.mkdtemp(prefix="mscodebase_"))

        path_hash = hashlib.md5(str(original_path).encode("utf-8")).hexdigest()
        safe_name = f"{path_hash}{original_path.suffix}"
        safe_path = self._temp_dir / safe_name

        try:
            if (
                not safe_path.exists()
                or safe_path.stat().st_mtime < original_path.stat().st_mtime
            ):
                shutil.copy2(original_path, safe_path)
        except Exception as e:
            logger.warning(f"Не удалось создать безопасную копию {original_path}: {e}")
            return original_path

        return safe_path

    def cleanup(self):
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
