"""Regression-тесты R3TF: fail-closed PID-lock (вариант A+, 2026-08-26).

Покрывают (AK-1..AK-8, REDTEAM_lock_attacks.md):
1. живой PID (в т.ч. с мёртвым корнем цепочки — venvwlauncher) → wait →
   LockBusyError, holder НЕ убит (инцидент 2026-08-26: PID 20052 killed by 12524);
2. мёртвый PID (Zed alive + child dead) → stale → steal;
3. PID reuse (create_time > started + tolerance) → stale → steal;
4. hostname чужой (v2) → AMBIGUOUS → wait, не трогаем;
5. неизвестная версия формата → AMBIGUOUS → wait;
6. lock race (N процессов, ровно один владелец);
7. termination race (lock пересоздан другим процессом во время steal) → fail-closed,
   чужой lock не удаляется;
8. stale lock (мёртвый pid) → steal без ожидания.

TerminateProcess удалён полностью (R3TF): DatabaseLock никогда не убивает
живые процессы — «break stale lock only on proof of death» (PostgreSQL/Qt/filelock).

Используют инжектируемый ProcessInspector (фейковые цепочки без реальных
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.core.indexing.database_lock import (
    DatabaseLock,
    LockBusyError,
    LockHolderState,
    ProcessInspector,
)

DEAD_PID = 999_999_999


def _write_lock(lock_path: Path, pid: int, started: float) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"pid": pid, "started": started, "role": "worker"}),
        encoding="utf-8",
    )


class FakeInspector(ProcessInspector):
    """Фейковый инспектор: фиксированные alive/create_time/parent_chain.

    Отслеживает вызовы is_alive (terminate-ожидание) — для проверки,
    что HEALTHY/AMBIGUOUS holder НЕ терминейтится.
    """

    def __init__(self, alive=True, create_time=None, chain=None):
        self._alive = alive
        self._ct = create_time
        self._chain = chain
        self.alive_calls: list = []

    def is_alive(self, pid: int) -> bool:
        self.alive_calls.append(pid)
        return self._alive

    def create_time(self, pid: int) -> float | None:
        return self._ct

    def parent_chain(self, pid: int, max_levels: int = 8):
        return self._chain


# ─── Классификация holder'а (unit) ─────────────────────────────

class TestClassifyHolder:
    def test_dead_pid_is_stale(self, tmp_path):
        insp = FakeInspector(alive=False)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        assert lock.classify_holder(DEAD_PID, time.time()) is LockHolderState.DEAD

    def test_own_pid_is_healthy(self, tmp_path):
        insp = FakeInspector(alive=True, create_time=time.time())
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        assert lock.classify_holder(os.getpid(), time.time()) is LockHolderState.HEALTHY

    def test_pid_reuse_is_stale(self, tmp_path):
        # lock записан 10s назад; процесс создан сейчас — не мог писать lock.
        started = time.time() - 10
        insp = FakeInspector(alive=True, create_time=time.time())
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        assert lock.classify_holder(12345, started) is LockHolderState.DEAD

    def test_healthy_chain_zed_alive(self, tmp_path):
        chain = [
            (12345, "python.exe", True),
            (22222, "python.exe", True),  # venvlauncher
            (33333, "powershell.exe", True),
            (44444, "Zed.exe", True),  # живой Zed
        ]
        # create_time == started (честный holder: процесс создан до acquire)
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=chain)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        assert lock.classify_holder(12345, time.time() - 5) is LockHolderState.HEALTHY

    def test_live_pid_with_dead_root_is_healthy(self, tmp_path):
        """R3TF: живой PID с мёртвым корнем цепочки → HEALTHY (wait),
        НЕ ORPHAN и НЕ kill. Это фикс инцидента 2026-08-26 (PID 20052:
        venvwlauncher-цепочка обрывается на мёртвом предке).
        """
        chain = [(12345, "python.exe", True), (77777, "?", False)]  # корень мёртв
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=chain)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        assert lock.classify_holder(12345, time.time() - 5) is LockHolderState.HEALTHY

    def test_live_pid_no_chain_is_healthy(self, tmp_path):
        """R3TF: chain=None больше не = AMBIGUOUS: живой PID с валидным
        create_time — HELD (fail-closed wait), независимо от цепочки."""
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=None)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        assert lock.classify_holder(12345, time.time() - 5) is LockHolderState.HEALTHY

    def test_live_pid_live_root_no_zed_is_healthy(self, tmp_path):
        """R3TF: живой, но не Zed-предок → HEALTHY (не AMBIGUOUS)."""
        chain = [
            (12345, "python.exe", True),
            (22222, "python.exe", True),  # живой, но не Zed
        ]
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=chain)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        assert lock.classify_holder(12345, time.time() - 5) is LockHolderState.HEALTHY

    def test_foreign_hostname_is_ambiguous(self, tmp_path):
        """R3TF (атака 6): lock с чужого host → AMBIGUOUS (PID непроверяем)."""
        insp = FakeInspector(alive=True, create_time=time.time() - 5)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        holder_data = {"pid": 12345, "started": time.time() - 5,
                       "hostname": "other-machine", "v": 2}
        assert lock.classify_holder(12345, time.time() - 5, holder_data) is LockHolderState.AMBIGUOUS

    def test_unsupported_version_is_ambiguous(self, tmp_path):
        """R3TF (атака 7): неизвестная версия формата → AMBIGUOUS (fail-closed)."""
        import socket
        insp = FakeInspector(alive=True, create_time=time.time() - 5)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        holder_data = {"pid": 12345, "started": time.time() - 5,
                       "hostname": socket.gethostname(), "v": 99}
        assert lock.classify_holder(12345, time.time() - 5, holder_data) is LockHolderState.AMBIGUOUS

    def test_own_host_v2_is_healthy(self, tmp_path):
        """Нормальный v2-lock (наш host, валидный create_time) → HEALTHY."""
        import socket
        insp = FakeInspector(alive=True, create_time=time.time() - 5)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        holder_data = {"pid": 12345, "started": time.time() - 5,
                       "hostname": socket.gethostname(), "v": 2}
        assert lock.classify_holder(12345, time.time() - 5, holder_data) is LockHolderState.HEALTHY


# ─── Кейс 1: healthy chain → wait → LockBusyError, holder НЕ убит ─

class TestHealthyHolder:
    def test_healthy_waits_and_soft_fails(self, tmp_path):
        chain = [(12345, "python.exe", True), (44444, "Zed.exe", True)]
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=chain)
        lock_path = tmp_path / ".write_lock"
        _write_lock(lock_path, 12345, time.time() - 5)

        lock = DatabaseLock(lock_path, wait_timeout=0.3, poll_interval=0.05,
                            holder_inspector=insp)
        t0 = time.monotonic()
        with pytest.raises(LockBusyError, match="still held by alive pid"):
            lock.acquire()
        elapsed = time.monotonic() - t0

        assert elapsed >= 0.25, f"wait слишком короткий: {elapsed:.2f}s"
        # holder НЕ терминейтится: is_alive вызывался только для проверок,
        # а lock-файл не тронут (steal не выполнялся).
        assert lock_path.exists()
        assert not lock.is_held()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == 12345

    def test_ambiguous_waits_and_soft_fails_no_kill(self, tmp_path):
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=None)
        lock_path = tmp_path / ".write_lock"
        _write_lock(lock_path, 12345, time.time() - 5)

        lock = DatabaseLock(lock_path, wait_timeout=0.3, poll_interval=0.05,
                            holder_inspector=insp)
        with pytest.raises(LockBusyError):
            lock.acquire()
        assert lock_path.exists()  # fail-closed: ничего не удалено


# ─── Кейс 2: Zed alive + child dead → stale → steal ────────────

class TestZedAliveChildDead:
    def test_dead_holder_stolen_even_with_live_zed_upstream(self, tmp_path):
        # holder (ребёнок Zed) мёртв; Zed выше жив. Мёртвый PID = stale,
        # независимо от живого предка — steal.
        insp = FakeInspector(alive=False)
        lock_path = tmp_path / ".write_lock"
        _write_lock(lock_path, DEAD_PID, time.time() - 3600)

        lock = DatabaseLock(lock_path, wait_timeout=0.3, holder_inspector=insp)
        lock.acquire()
        try:
            assert lock.is_held()
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            assert data["pid"] == os.getpid()
        finally:
            lock.release()


# ─── Кейс 3: живой holder (мёртвый корень цепочки) → wait → LockBusyError, НЕ kill ─

class TestLiveHolderWithDeadRoot:
    """R3TF (инцидент 2026-08-26): живой процесс с мёртвым предком больше
    НЕ терминейтится — TerminateProcess удалён. Venvwlauncher-цепочки живых
    MCP дают ложный «orphan»-вид, но holder HELD → LockBusyError (fail-closed).
    """

    def test_live_holder_with_dead_root_waits_and_soft_fails(self, tmp_path):
        chain = [(12345, "python.exe", True), (77777, "?", False)]
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=chain)
        lock_path = tmp_path / ".write_lock"
        _write_lock(lock_path, 12345, time.time() - 5)

        lock = DatabaseLock(lock_path, wait_timeout=0.3, poll_interval=0.05,
                            holder_inspector=insp)
        with pytest.raises(LockBusyError, match="still held by alive pid"):
            lock.acquire()
        # holder НЕ убит и lock не тронут (TerminateProcess отсутствует)
        assert lock_path.exists()
        assert not lock.is_held()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == 12345
        # terminate-путь не вызывался: нет ни одного _terminate_holder вызова
        assert not hasattr(lock, "_terminate_holder"), "TerminateProcess путь удалён"

    def test_fake_lock_foreign_live_pid_not_killed(self, tmp_path):
        """R3TF (атака 1): поддельный lock с чужим ЖИВЫМ PID (например
        explorer.exe) → HELD (wait → LockBusyError), НЕ TerminateProcess.
        """
        import socket
        insp = FakeInspector(alive=True, create_time=time.time() - 5)
        lock_path = tmp_path / ".write_lock"
        _write_lock(lock_path, 12345, time.time() - 5)
        # v2 формат, чужой hostname отсутствует → наш host, но PID чужой живой
        lock_path.write_text(json.dumps({
            "v": 2, "pid": 12345, "started": time.time() - 5,
            "role": "worker", "hostname": socket.gethostname(),
        }), encoding="utf-8")

        lock = DatabaseLock(lock_path, wait_timeout=0.3, poll_interval=0.05,
                            holder_inspector=insp)
        with pytest.raises(LockBusyError):
            lock.acquire()
        assert lock_path.exists()  # чужой lock не удалён, никто не убит


# ─── Кейс 4: PID reuse → steal ─────────────────────────────────

class TestPidReuse:
    def test_pid_reuse_stolen(self, tmp_path):
        # lock записан 10s назад (старый владелец мёртв), PID переиспользован
        # новым процессом, созданным «сейчас» (create_time > started).
        started = time.time() - 10
        insp = FakeInspector(alive=True, create_time=time.time())
        lock_path = tmp_path / ".write_lock"
        _write_lock(lock_path, 12345, started)

        lock = DatabaseLock(lock_path, wait_timeout=0.3, holder_inspector=insp)
        lock.acquire()
        try:
            assert lock.is_held()
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            assert data["pid"] == os.getpid()
        finally:
            lock.release()


# ─── Кейсы 5/8: lock race + concurrent acquisition ────────────

class TestConcurrentAcquisition:
    def test_exactly_one_winner_concurrent(self, tmp_path):
        n = 8
        results: list = []
        barrier = threading.Barrier(n)

        def _try():
            lock = DatabaseLock(tmp_path / ".write_lock", wait_timeout=0.3,
                                poll_interval=0.05)
            barrier.wait()
            try:
                lock.acquire()
                results.append(("acquired", lock))
            except (RuntimeError, LockBusyError):
                results.append(("failed", None))
            except Exception as exc:  # noqa: BLE001 — тест фиксирует любой сбой
                results.append((f"unexpected:{type(exc).__name__}", None))

        threads = [threading.Thread(target=_try) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [r for r in results if r[0] == "acquired"]
        failed = [r for r in results if r[0] == "failed"]
        assert len(winners) == 1, f"ожидали 1 winner, получили {len(winners)}"
        assert len(failed) == n - 1
        for _, lock in winners:
            lock.release()


# ─── Кейс 6: steal-race (DEAD) ──────────────────────────────

class TestStealRace:
    def test_fresh_owner_not_stolen_during_steal(self, tmp_path, monkeypatch):
        """Lock пересоздан другим процессом до unlink — чужой свежий lock
        не удаляется (fail-closed). Путь steal теперь ДОСТИЖИМ только для
        мёртвого holder'а (DEAD): TerminateProcess удалён, живой holder
        → HELD, steal не начинается.
        """
        insp = FakeInspector(alive=False)  # мёртвый holder → DEAD → steal
        lock = DatabaseLock(tmp_path / ".write_lock", wait_timeout=0.2,
                             holder_inspector=insp)
        # R3TF: _terminate_holder больше не существует в классе —
        # assert отсутствия kill-пути.
        assert not hasattr(lock, "_terminate_holder")

        started_old = time.time() - 5
        _write_lock(tmp_path / ".write_lock", 999_999_998, started_old)

        # Первый вызов _read_holder — мёртвый holder (DEAD); второй (после
        # классификации, перед unlink) — lock уже пересоздан ДРУГИМ процессом.
        calls = {"n": 0}

        def _fake_read():
            calls["n"] += 1
            if calls["n"] == 1:
                return {"pid": 999_999_998, "started": started_old}
            return {"pid": 424_242, "started": time.time()}  # свежий владелец

        monkeypatch.setattr(lock, "_read_holder", _fake_read)

        with pytest.raises(LockBusyError, match="пересоздан другим процессом"):
            lock.acquire()
        # чужой lock не удалён (файл на диске не тронут — данные прежние)
        assert (tmp_path / ".write_lock").exists()
        data = json.loads((tmp_path / ".write_lock").read_text(encoding="utf-8"))
        assert data["pid"] == 999_999_998
        assert not lock.is_held()


# ─── Кейс 7: stale lock ────────────────────────────────────────

class TestStaleLock:
    def test_dead_pid_stolen_immediately(self, tmp_path):
        insp = FakeInspector(alive=False)
        lock_path = tmp_path / ".write_lock"
        _write_lock(lock_path, DEAD_PID, time.time() - 3600)

        # wait_timeout не участвует в DEAD-пути (только HEALTHY/AMBIGUOUS ждут
        # до него): 0.8 — просто запас для ассерта ниже.
        # Порог 0.5: fast-path steal измерен до 0.27s на загруженном CI-раннере
        # (grace-повтор _read_holder спит 0.25s) — 0.2 был флейком; регрессия
        # «steal ждёт полный wait_timeout» (0.8s) всё ещё ловится запасом 0.3s.
        lock = DatabaseLock(lock_path, wait_timeout=0.8, holder_inspector=insp)
        t0 = time.monotonic()
        lock.acquire()  # не должен ждать
        elapsed = time.monotonic() - t0
        try:
            assert lock.is_held()
            assert elapsed < 0.5, f"steal занял {elapsed:.2f}s — ждал зря"
        finally:
            lock.release()


# ─── Live-тест: реальный живой процесс НЕ убивается (R3TF) ────

class TestLiveProcessNotKilled:
    """Регрессия инцидента 2026-08-26: живой процесс (даже с «мёртвым
    предком»-видом) → HELD → LockBusyError, НИКОГДА TerminateProcess.
    """

    @pytest.mark.skipif(sys.platform != "win32", reason="Процесс-тест — Windows-only")
    def test_real_live_process_not_terminated(self, tmp_path):
        """Реальный дочерний процесс держит lock — второй acquire НЕ убивает
        его, а ждёт и падает с LockBusyError (сценарий PID 20052)."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            lock_path = tmp_path / ".write_lock"
            # started пишем ПОСЛЕ создания процесса (create_time <= started+2,
            # иначе create_time-guard отнесёт к PID-reuse).
            _write_lock(lock_path, proc.pid, time.time())

            lock = DatabaseLock(lock_path, wait_timeout=0.3, poll_interval=0.05)
            t0 = time.monotonic()
            with pytest.raises(LockBusyError, match="still held by alive pid"):
                lock.acquire()
            elapsed = time.monotonic() - t0
            # HELD-путь ждёт ≤ wait_timeout (0.3s), потом LockBusyError
            assert 0.2 <= elapsed < 1.5, f"HELD-wait занял {elapsed:.2f}s"
            assert not lock.is_held()
            # ЖИВОЙ процесс НЕ убит (центральный инвариант R3TF!)
            assert proc.poll() is None, "holder БЫЛ УБИТ — регрессия инцидента!"
            assert lock_path.exists()  # чужой lock не тронут
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
