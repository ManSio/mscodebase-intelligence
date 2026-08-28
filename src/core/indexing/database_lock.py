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

Self-healing (WS9, KNOWN_ISSUES#2026-08-08-multiwindow-pidlock) —
первая версия использовала parent-chain + TerminateProcess «зомби»:
цепочка venvwlauncher-процесса обрывается на мёртвом предке ДО живого Zed
→ живой MCP другого окна убивался (инцидент 2026-08-26, PID 20052
killed by 12524; REDTEAM_lock_attacks.md, атаки 1-4).

R3TF (2026-08-26) — «break stale lock only on proof of death»
(PostgreSQL postmaster.pid / Qt QLockFile / python filelock):
- PID validation: мёртвый PID → steal (как раньше);
- create_time guard: процесс создан ПОЗЖЕ записи lock (create_time >
  started + tolerance) → PID-reuse/подделка → steal;
- hostname в lock (v2): lock с другой машины → AMBIGUOUS (PID чужого
  хоста непроверяем локально) → ждём, не трогаем;
- любой ЖИВОЙ PID с совпадающим create_time → HEALTHY (wait → soft
  LockBusyError), НИКОГДА не терминейтится. TerminateProcess удалён.
- parent_chain остаётся только для диагностики (server_factory,
  lsp_project_bridge), из решения исключён.

Инцидент-фикс: `classify_holder` больше НЕ возвращает ORPHAN, `acquire()`
не вызывает `_terminate_holder`. Fail-closed: непроверяемый holder → ждём.

Инжектируемый ProcessInspector позволяет тестам симулировать цепочки
процессов без реальных OS-процессов (Linux CI).

DatabaseLock — «один хозяин соединения» (DatabaseGateway): единственная
точка захвата/освобождения блокировки на директорию LanceDB.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("mscodebase_server.database_lock")

LOCK_ROLE = "worker"

# Версия формата lock-файла (hostname добавлен в v2, R3TF-harden 2026-08-26).
# Несовпадающая/отсутствующая версия → AMBIGUOUS (fail-closed, не трогаем).
LOCK_FORMAT_VERSION = 2

# WS9: дефолтное ожидание сокращено 30s → 8s (Zed request timeout = 60s/запрос,
# но 8s достаточно для легитимного контеншена; мягкий LockBusyError вместо
# жёсткого RuntimeError-краха при живом holder'е).
DEFAULT_WAIT_TIMEOUT = 8.0
# create_time guard: процесс создан позже записи lock более чем на это
# значение → lock не от него (PID-reuse / подделка).
CREATE_TIME_TOLERANCE = 2.0
# Сколько ждать освобождения lock-файла (unlink) при PermissionError
# (Windows держит fd мгновение после смерти holder'а).
UNLINK_RETRY_TIMEOUT = 5.0
# Максимальная глубина walk по цепочке родителей (диагностика, НЕ для решения).
PARENT_CHAIN_MAX_LEVELS = 8


class LockHolderState(Enum):
    """Классификация holder'а lock-файла (см. classify_holder).

    ORPHAN удалён (R3TF 2026-08-26): живой PID больше НЕ может быть
    классифицирован как «зомби» — TerminateProcess по эвристике убивал
    живые MCP. Индустрия: «break stale lock only on proof of death».
    """

    DEAD = "dead"  # PID мёртв или PID-reuse → steal
    HEALTHY = "healthy"  # живой процесс (наш или другого окна) → wait
    AMBIGUOUS = "ambiguous"  # не можем проверить (чужой host/format) → fail-closed wait


class LockBusyError(RuntimeError):
    """Soft-failure: лок занят здоровым процессом (или неопределимым).

    Подкласс RuntimeError — существующие обработчики (db_manager) и тесты,
    ловящие RuntimeError, продолжают работать. Holder НЕ убивается.
    """


class ProcessInspector:
    """Интроспекция процессов для классификации holder'а lock-файла.

    Инжектируется в тестах; default — платформенная реализация
    (Windows: ctypes/OpenProcess/GetProcessTimes/Toolhelp32; Unix: os.kill,
    без parent-chain и create_time → соответствующие методы возвращают None).
    """

    def is_alive(self, pid: int) -> bool:
        """Жив ли процесс с данным PID (в т.ч. завершённый, не очищенный ОС)."""
        return DatabaseLock._is_pid_alive(pid)

    def create_time(self, pid: int) -> Optional[float]:
        """Unix-секунды старта процесса или None (платформа не поддерживает)."""
        return None

    def parent_chain(
        self, pid: int, max_levels: int = PARENT_CHAIN_MAX_LEVELS
    ) -> Optional[List[Tuple[int, str, bool]]]:
        """Цепочка (pid, имя, alive) от holder'а к корню (≤ max_levels).

        None — платформа не поддерживает / недоступно (fail-closed).
        """
        return None


class WindowsProcessInspector(ProcessInspector):
    """Реализация через Win32 API (без psutil — см. WS9 psutil-вывод).

    - живость: OpenProcess + GetExitCodeProcess (STILL_ACTIVE=259);
    - create_time: GetProcessTimes (FILETIME → unix-секунды);
    - parent chain: Toolhelp32Snapshot (Process32First/Next).
    """

    def is_alive(self, pid: int) -> bool:
        return DatabaseLock._is_pid_alive(pid)

    def create_time(self, pid: int) -> Optional[float]:
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                class _FT(ctypes.Structure):
                    _fields_ = [
                        ("dwLowDateTime", wintypes.DWORD),
                        ("dwHighDateTime", wintypes.DWORD),
                    ]

                create, exit_, kern, user = _FT(), _FT(), _FT(), _FT()
                if not kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(create),
                    ctypes.byref(exit_),
                    ctypes.byref(kern),
                    ctypes.byref(user),
                ):
                    return None
                ft = (create.dwHighDateTime << 32) | create.dwLowDateTime
                # FILETIME: 100ns с 1601-01-01 → unix-секунды
                return ft / 10_000_000 - 11644473600
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 — диагностика, не критично
            return None

    def parent_chain(
        self, pid: int, max_levels: int = PARENT_CHAIN_MAX_LEVELS
    ) -> Optional[List[Tuple[int, str, bool]]]:
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            TH32CS_SNAPPROCESS = 0x00000002
            snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if snapshot == -1:
                return None
            table: dict = {}
            try:
                class _PE32(ctypes.Structure):
                    _fields_ = [
                        ("dwSize", wintypes.DWORD),
                        ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_char * 260),
                    ]

                entry = _PE32()
                entry.dwSize = ctypes.sizeof(_PE32)
                ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
                while ok:
                    table[entry.th32ProcessID] = {
                        "ppid": entry.th32ParentProcessID,
                        "name": entry.szExeFile.decode("ascii", "replace"),
                    }
                    ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
            finally:
                kernel32.CloseHandle(snapshot)

            chain: List[Tuple[int, str, bool]] = []
            cur = pid
            for _ in range(max_levels):
                info = table.get(cur)
                if info is None:
                    # Мёртвые процессы отсутствуют в Toolhelp-снапшоте;
                    # живость проверяем OpenProcess (ловит PID-reuse).
                    alive = self.is_alive(cur)
                    chain.append((cur, "?", alive))
                    if not alive:
                        break
                    break
                alive = self.is_alive(cur)
                chain.append((cur, info["name"], alive))
                if not alive:
                    break
                nxt = info["ppid"]
                if nxt == cur or nxt == 0:
                    break
                cur = nxt
            return chain
        except Exception:  # noqa: BLE001 — диагностика, не критично
            return None


class DatabaseLock:
    """Эксклюзивный lock на директорию БД через файл `.write_lock`.

    Args:
        lock_path: путь к lock-файлу (обычно `db_path / ".write_lock"`).
        wait_timeout: сколько секунд ждать освобождения lock-а живым
            процессом (по умолчанию 8 — WS9; мягкий LockBusyError).
        retry_attempts: попыток повторного os.open после steal
            (гонка между unlink и open).
        poll_interval: шаг опроса в цикле ожидания.
        holder_inspector: ProcessInspector для классификации holder'а
            (по умолчанию — платформенный).
        unlink_retry_timeout: сколько ждать освобождения lock-файла (unlink)
            при PermissionError.
        create_time_tolerance: допуск create_time guard (PID-reuse).
    """

    def __init__(
        self,
        lock_path: Path,
        wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
        retry_attempts: int = 5,
        poll_interval: float = 0.25,
        *,
        holder_inspector: Optional[ProcessInspector] = None,
        unlink_retry_timeout: float = UNLINK_RETRY_TIMEOUT,
        create_time_tolerance: float = CREATE_TIME_TOLERANCE,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.wait_timeout = wait_timeout
        self.retry_attempts = retry_attempts
        self._poll_interval = poll_interval
        self._unlink_retry_timeout = unlink_retry_timeout
        self._create_time_tolerance = create_time_tolerance
        self._inspector = holder_inspector or self._make_default_inspector()
        self._fd: Optional[int] = None
        self._acquired = False

    @staticmethod
    def _make_default_inspector() -> ProcessInspector:
        if sys.platform == "win32":
            return WindowsProcessInspector()
        return ProcessInspector()

    # ══════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════

    def acquire(self) -> None:
        """Захватывает lock.

        Raises:
            LockBusyError (RuntimeError): lock занят живым/неопределимым
                процессом дольше wait_timeout, или гонка при retry.
                Holder НЕ убивается никогда (R3TF: только proof-of-death
                steal: мёртвый PID / подтверждённый PID-reuse).
        """
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
        holder = self._read_holder()
        holder_pid = holder["pid"] if holder is not None else None
        holder_started = (holder.get("started") or 0) if holder is not None else 0

        if holder is not None and holder_pid is not None:
            state = self.classify_holder(holder_pid, holder_started, holder_data=holder)
            if state is LockHolderState.DEAD:
                # steal обрабатывается кодом ниже (после TOCTOU-проверки).
                pass
            else:
                # HEALTHY или AMBIGUOUS — живой/непроверяемый holder:
                # ждём до wait_timeout, holder НЕ трогаем (fail-closed).
                logger.warning(
                    f"PID lock held by {state.value} pid={holder_pid}, "
                    f"waiting up to {self.wait_timeout}s..."
                )
                self._wait_for_release(holder_pid)

        # Holder мёртв / lock освобождён / lock битый — забираем lock.
        # TOCTOU-guard (death/lock race): удаляем файл ТОЛЬКО если это всё ещё
        # ТОТ ЖЕ lock, который мы классифицировали.
        if self.lock_path.exists():
            cur = self._read_holder()
            same_holder = (
                cur is not None
                and cur.get("pid") == holder_pid
                and (cur.get("started") or 0) == holder_started
            )
            same_stale = holder is None and cur is None
            if not (same_holder or same_stale):
                # Lock пересоздан другим процессом после нашей классификации —
                # чужой свежий lock не трогаем (fail-closed).
                raise LockBusyError(
                    f"PID lock пересоздан другим процессом (pid={cur.get('pid') if cur else '?'}) "
                    f"во время ожидания — retry позже"
                )
            try:
                self._unlink_with_retry(holder_pid)
            except PermissionError:
                # Windows: файл не освободился за unlink_retry_timeout (живой
                # процесс держит fd) — некража, fail-closed.
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
        raise LockBusyError(
            "PID lock race: другой процесс захватил lock во время retry — "
            "retry позже"
        )

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
    # Holder classification (WS9)
    # ══════════════════════════════════════════════════════

    def classify_holder(
        self, pid: int, started: float, holder_data: Optional[dict] = None
    ) -> LockHolderState:
        """Классифицирует holder'а lock-файла по интроспекции процесса.

        R3TF (2026-08-26): «break stale lock only on proof of death».
        Живой процесс НИКОГДА не терминейтится — эвристика цепочки
        родителей удалена (убивала живые MCP другого окна, инцидент
        2026-08-26). Порядок проверок:
        1. hostname не совпадает (v2) / формат неподдерживаемый → AMBIGUOUS
           (PID чужой машины локально непроверяем; непонятный формат —
           fail-closed, не трогаем).
        2. PID мёртв → DEAD (stale, steal).
        3. pid == наш процесс → HEALTHY (self-hold; не может быть PID-reuse).
        4. create_time guard: процесс создан ПОСЛЕ записи lock
           (create_time > started + tolerance) → PID-reuse/подделка → DEAD.
        5. Живой PID с валидным create_time → HEALTHY (wait, fail-closed).
        """
        if holder_data is not None:
            holder_host = holder_data.get("hostname")
            if holder_host and holder_host != socket.gethostname():
                logger.warning(
                    f"PID lock from foreign host {holder_host!r} "
                    f"(this host {socket.gethostname()!r}) — cannot verify PID, held"
                )
                return LockHolderState.AMBIGUOUS
            holder_v = holder_data.get("v")
            if holder_v is not None and holder_v != LOCK_FORMAT_VERSION:
                logger.warning(
                    f"PID lock format v{holder_v} unsupported (current v"
                    f"{LOCK_FORMAT_VERSION}) — held (fail-closed)"
                )
                return LockHolderState.AMBIGUOUS

        if not self._inspector.is_alive(pid):
            return LockHolderState.DEAD
        if pid == os.getpid():
            return LockHolderState.HEALTHY

        ct = self._inspector.create_time(pid)
        if ct is not None and ct > started + self._create_time_tolerance:
            # Направленный инвариант: процесс не мог записать lock до своего
            # создания. create_time <= started всегда для честного holder'а
            # (независимо от лага между стартом процесса и acquire).
            logger.warning(
                f"PID lock PID-reuse: pid={pid} create_time={ct:.0f} "
                f"> started={started:.0f} — lock не от этого процесса, stale"
            )
            return LockHolderState.DEAD

        # Живой PID с честным create_time — держим как HELD.
        # Parent-chain здесь НЕ участвует: venvwlauncher-цепочки живых MCP
        # обрываются на мёртвом предке ДО живого Zed (ложный ORPHAN → kill).
        return LockHolderState.HEALTHY

    def _unlink_with_retry(self, holder_pid: Optional[int]) -> None:
        """Удаляет lock-файл с retry против Windows PermissionError.

        После смерти holder'а файловый дескриптор (os.open в holder'е) может
        ещё мгновение держаться ядром → unlink бросает PermissionError.
        Повторяем до unlink_retry_timeout; по таймауту пробрасываем
        PermissionError (fail-closed, некража).
        """
        deadline = time.monotonic() + self._unlink_retry_timeout
        while True:
            try:
                self.lock_path.unlink(missing_ok=True)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)

    # ══════════════════════════════════════════════════════
    # Internals
    # ══════════════════════════════════════════════════════

    def _write_owner(self, fd: int) -> None:
        """Пишет PID + timestamp + hostname (v2) в lock-файл и синхронизирует.

        hostname обязателен (R3TF-атака 6): на сетевом share PID другой
        машины непроверяем локально — классификация по hostname даёт
        AMBIGUOUS (fail-closed) вместо ложного steal/HEALTHY.
        """
        self._fd = fd
        lock_data = json.dumps(
            {
                "v": LOCK_FORMAT_VERSION,
                "pid": os.getpid(),
                "started": time.time(),
                "role": LOCK_ROLE,
                "hostname": socket.gethostname(),
            }
        ).encode()
        os.write(fd, lock_data)
        os.fsync(fd)

    def _read_holder(self) -> Optional[dict]:
        """Возвращает данные владельца lock-файла или None (битый/нечитаемый).

        Grace-период: нечитаемый/пустой JSON НЕ трактуется как stale сразу —
        файл мог быть только что создан (O_EXCL), владелец ещё не записал
        owner (окно между os.open и os.fsync). На Unix unlink активного
        файла разрешён, поэтому немедленный steal даёт ДВА писателя
        (test_race_exactly_one_winner на Linux: Expected 1 winner, got 2).
        Чтение повторяется retry_attempts раз с паузой poll_interval,
        после чего lock считается битым (stale).
        """
        for _attempt in range(self.retry_attempts):
            try:
                with open(self.lock_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {
                    "pid": data.get("pid"),
                    "started": data.get("started") or 0,
                    "hostname": data.get("hostname"),
                    "v": data.get("v"),
                }
            except (json.JSONDecodeError, OSError):
                time.sleep(self._poll_interval)
        logger.warning(
            f"PID lock unreadable after {self.retry_attempts} attempts — "
            f"treating as stale: {self.lock_path}"
        )
        return None

    def _wait_for_release(self, holder_pid: int) -> None:
        """Ждёт освобождения lock-а живым процессом; по таймауту — LockBusyError.

        P1-14 audit: раньше при таймауте молча падал вниз БЕЗ захвата лока
        (писатель работал без блокировки). Теперь — явная ошибка.
        WS9: мягкая LockBusyError (holder не убивается, retry возможен).
        """
        deadline = time.monotonic() + self.wait_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LockBusyError(
                    f"PID lock still held by alive pid={holder_pid} "
                    f"after {self.wait_timeout}s — база занята другим окном MCP; "
                    f"retry позже (holder не тронут)"
                )
            time.sleep(min(self._poll_interval, remaining))
            if not self._inspector.is_alive(holder_pid):
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
