"""
MSCodebase Intelligence — Безопасное управление путями файловой системы
"""

import atexit
import hashlib
import logging
import os
import shutil
import tempfile
import threading
import weakref
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
    """Менеджер безопасных путей для изоляции не-ASCII символов и длинных путей.

    Изменения (INC-53EC / REFC-06): tempdir, создаваемый в get_safe_path,
    теперь чистится через atexit + weakref.finalize. Без этого файлы
    копились в %TEMP%/mscodebase_* между рестартами MCP/LSP.
    """

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self._temp_dir: Optional[Path] = None
        self._lock = threading.Lock()
        # weakref.finalize срабатывает при GC объекта. ateatxit —
        # при завершении процесса. Двойная страховка.
        self._finalizer = weakref.finalize(
            self, self._finalize_tempdir, None
        )
        # Финальный обработчик для случая, если процесс убивают
        # через os._exit без atexit (используется в heartbeat shutdown).
        atexit.register(self.cleanup)

    def requires_safe_path(self, path_str: str) -> bool:
        if not path_str.isascii() or " " in path_str or len(path_str) > 200:
            return True
        return False

    def is_safe_to_process(self, path: Path) -> bool:
        """Проверяет, можно ли обрабатывать путь напрямую.

        Возвращает True для обычных путей (безопасно),
        False - если требуется специальная обработка (не-ASCII, длинный).
        """
        return not self.requires_safe_path(str(path))

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

    @staticmethod
    def _finalize_tempdir(path: Optional[Path]) -> None:
        """Static finalizer для weakref.finalize (не держит self)."""
        if path and path.exists():
            try:
                shutil.rmtree(path, ignore_errors=True)
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass

    def cleanup(self) -> None:
        """Удаляет временную папку. Идемпотентен."""
        with self._lock:
            td = self._temp_dir
            self._temp_dir = None
        if td and td.exists():
            try:
                shutil.rmtree(td, ignore_errors=True)
                logger.debug(f"🧹 Временная папка удалена: {td}")
            except Exception as e:
                logger.warning(
                    f"Ошибка удаления временной папки {td}: {e}"
                )
