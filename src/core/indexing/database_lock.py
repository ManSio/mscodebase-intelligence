"""DatabaseLock — межпроцессный single-writer lock на директорию БД.

Выделено из LanceDBManager._acquire_pid_lock (P1-14 / P1-15 / INC-6C62):
атомарный lock-файл с PID + timestamp. Гарантирует, что только ОДИН
worker-процесс пишет в БД; второй ждёт до wait_timeout или падает с
RuntimeError (не молча работает без блокировки).

Семантика сохранена 1-в-1 из оригинальной реализации:
- O_CREAT|O_EXCL — атомарное создание lock-файла;
- lock занят ЖИВЫМ PID → ждём до wait_timeout (poll по poll_interval);
- lock занят МЁРТВЫМ PID или битый (invalid JSON) → steal (забираем);
- unlink → retry-loop (retry_attempts) против гонки с другим процессом;
- release() идемпотентен и удаляет файл ТОЛЬКО если lock наш (_acquired) —
  в отличие от оригинала, не может снять чужой lock на Unix.

DatabaseLock — «один хозяин соединения» (DatabaseGateway): единственная
точка захвата/освобождения блокировки на директорию LanceDB.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mscodebase_server.database_lock")

LOCK_ROLE = "worker"


class DatabaseLock:
    """Эксклюзивный lock на директорию БД через файл `.write_lock`.

    Args:
        lock_path: путь к lock-файлу (обычно `db_path / ".write_lock"`).
        wait_timeout: сколько секунд ждать освобождения lock-а живым
            процессом (по умолчанию 30 — как в оригинале).
        retry_attempts: попыток повторного os.open после steal
            (гонка между unlink и open).
        poll_interval: шаг опроса в цикле ожидания.
    """

    def __init__(
        self,
        lock_path: Path,
        wait_timeout: float = 30.0,
        retry_attempts: int = 5,
        poll_interval: float = 0.25,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.wait_timeout = wait_timeout
        self.retry_attempts = retry_attempts
        self._poll_interval = poll_interval
        self._fd: Optional[int] = None
        self._acquired = False

    # ══════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════

    def acquire(self) -> None:
        """Захватывает lock. RuntimeError если lock занят живым процессом
        дольше wait_timeout или не удаётся забрать stale-lock."""
        if self._acquired:
            return

        # Убеждаемся, что parent dir существует (LanceDB может не создать
        # его до первого connect).
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            fd = os.open(
                str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
            )
            self._write_owner(fd)
            self._acquired = True
            logger.info(f"🔒 PID lock acquired: {self.lock_path} (pid={os.getpid()})")
            return
        except FileExistsError:
            pass

        # Lock существует — читаем данные владельца.
        holder_pid = self._read_holder_pid()

        if holder_pid is not None and self._is_pid_alive(holder_pid):
            # Lock занят живым процессом — ждём до wait_timeout.
            logger.warning(f"PID lock held by alive pid={holder_pid}, waiting...")
            self._wait_for_release(holder_pid)

        # Holder мёртв / lock освобождён / lock битый — забираем lock.
        if self.lock_path.exists():
            try:
                self.lock_path.unlink(missing_ok=True)
            except PermissionError:
                # Windows: файл занят живым процессом — некража.
                raise RuntimeError(
                    f"Cannot steal PID lock from pid={holder_pid}: file in use"
                )

        # Retry-loop на гонку: другой процесс может создать lock между
        # unlink и os.open (P1-14 audit — раньше был один шанс и краш).
        for _attempt in range(self.retry_attempts):
            try:
                fd = os.open(
                    str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
                )
                self._write_owner(fd)
                self._acquired = True
                logger.info(
                    f"🔒 PID lock acquired (after retry): {self.lock_path} (pid={os.getpid()})"
                )
                return
            except FileExistsError:
                time.sleep(0.5)
        raise RuntimeError("PID lock race: another process acquired lock during retry")

    def release(self) -> None:
        """Освобождает lock. Идемпотентен; удаляет файл только если lock наш."""
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None
        if self._acquired:
            try:
                self.lock_path.unlink(missing_ok=True)
                logger.info(f"🔓 PID lock released: {self.lock_path}")
            except Exception:
                pass
            self._acquired = False

    def is_held(self) -> bool:
        """True если lock захвачен ЭТИМ экземпляром."""
        return self._acquired

    def __enter__(self) -> "DatabaseLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    def __del__(self):
        """Ensure lock is released on object destruction."""
        try:
            self.release()
        except Exception:
            pass

    # ══════════════════════════════════════════════════════
    # Internals
    # ══════════════════════════════════════════════════════

    def _write_owner(self, fd: int) -> None:
        """Пишет PID + timestamp в lock-файл и синхронизирует на диск."""
        self._fd = fd
        lock_data = json.dumps(
            {
                "pid": os.getpid(),
                "started": time.time(),
                "role": LOCK_ROLE,
            }
        ).encode()
        os.write(fd, lock_data)
        os.fsync(fd)

    def _read_holder_pid(self) -> Optional[int]:
        """Возвращает PID владельца lock-файла или None (битый/нечитаемый)."""
        try:
            with open(self.lock_path, "r") as f:
                data = json.load(f)
            return data.get("pid")
        except (json.JSONDecodeError, OSError):
            return None  # битый/нечитаемый lock — трактуем как stale

    def _wait_for_release(self, holder_pid: int) -> None:
        """Ждёт освобождения lock-а живым процессом; по таймауту — RuntimeError.

        P1-14 audit: раньше при таймауте молча падал вниз БЕЗ захвата лока
        (писатель работал без блокировки). Теперь — явный крах.
        """
        deadline = time.monotonic() + self.wait_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"PID lock still held by alive pid={holder_pid} "
                    f"after {self.wait_timeout}s — другой процесс пишет в эту БД"
                )
            time.sleep(min(self._poll_interval, remaining))
            if not self._is_pid_alive(holder_pid):
                logger.info(f"Previous process pid={holder_pid} exited, proceeding")
                return
            if not self.lock_path.exists():
                return

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if a PID is alive (cross-platform).

        На Unix: os.kill(pid, 0) — signal 0, ProcessLookupError = dead.
        На Windows: os.kill для чужих процессов кидает WinError 11 (OSError)
        даже если процесс жив. Используем ctypes.OpenProcess + GetExitCodeProcess.

        INC-6471-fix: одного OpenProcess НЕДОСТАТОЧНО — он возвращает handle
        и для завершённого, но не очищенного процесса (exit_code != 259,
        STILL_ACTIVE). Без GetExitCodeProcess мёртвый владелец lock-файла
        выглядел живым → новый процесс ждал wait_timeout и падал с
        RuntimeError вместо steal (заблокированный запуск MCP).
        """
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.windll.kernel32
                STILL_ACTIVE = 259
                # PROCESS_QUERY_LIMITED_INFORMATION (0x1000) — минимальные права
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if not handle:
                    # ERROR_INVALID_PARAMETER (87) — процесс не существует
                    return False
                try:
                    code = wintypes.DWORD()
                    ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                    return bool(ok) and code.value == STILL_ACTIVE
                finally:
                    kernel32.CloseHandle(handle)
            except Exception:
                # fallback: если ctypes недоступен, считаем живым (safe side)
                return True

        # Unix: os.kill(pid, 0)
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            # PermissionError и др. — процесс существует, но недоступен
            return True
