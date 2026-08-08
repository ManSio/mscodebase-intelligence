"""Regression-тесты WS9: self-healing PID-lock (вариант C).

Покрывают (AC-1..AC-8, KNOWN_ISSUES#2026-08-08-multiwindow-pidlock):
1. healthy Zed/Python/LSP chain → wait ≤ wait_timeout → LockBusyError (holder НЕ убит);
2. Zed alive + child dead (holder мёртв) → stale → steal;
3. orphan root (holder жив, корень цепочки мёртв) → terminate + steal;
4. PID reuse (create_time > started + tolerance) → stale → steal;
5. lock race (N процессов, ровно один владелец);
6. termination race (lock пересоздан другим процессом во время steal) → fail-closed,
   чужой lock не удаляется;
7. stale lock (мёртвый pid) → steal без ожидания;
8. concurrent acquisition (N потоков: 1 winner, остальные LockBusyError).

Используют инжектируемый ProcessInspector (фейковые цепочки без реальных
OS-процессов — работает на Linux CI). Windows-only live-тест TerminateProcess —
skipif.
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
    WindowsProcessInspector,
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

    def test_orphan_root_dead(self, tmp_path):
        chain = [(12345, "python.exe", True), (77777, "?", False)]  # корень мёртв
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=chain)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        assert lock.classify_holder(12345, time.time() - 5) is LockHolderState.ORPHAN

    def test_ambiguous_no_chain(self, tmp_path):
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=None)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        assert lock.classify_holder(12345, time.time() - 5) is LockHolderState.AMBIGUOUS

    def test_ambiguous_live_root_no_zed(self, tmp_path):
        chain = [
            (12345, "python.exe", True),
            (22222, "python.exe", True),  # живой, но не Zed
        ]
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=chain)
        lock = DatabaseLock(tmp_path / ".write_lock", holder_inspector=insp)
        assert lock.classify_holder(12345, time.time() - 5) is LockHolderState.AMBIGUOUS


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


# ─── Кейс 3: orphan root → terminate → steal ───────────────────

class TestOrphanHolder:
    def test_orphan_terminated_and_stolen(self, tmp_path, monkeypatch):
        chain = [(12345, "python.exe", True), (77777, "?", False)]
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=chain)
        lock_path = tmp_path / ".write_lock"
        _write_lock(lock_path, 12345, time.time() - 5)

        lock = DatabaseLock(lock_path, wait_timeout=0.3, holder_inspector=insp)
        terminated = []
        monkeypatch.setattr(lock, "_terminate_holder",
                            lambda pid: terminated.append(pid) or True)
        lock.acquire()
        try:
            assert terminated == [12345], "зомби должен быть терминейтнут"
            assert lock.is_held()
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            assert data["pid"] == os.getpid()
        finally:
            lock.release()

    def test_orphan_terminate_fails_soft(self, tmp_path, monkeypatch):
        chain = [(12345, "python.exe", True), (77777, "?", False)]
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=chain)
        lock_path = tmp_path / ".write_lock"
        _write_lock(lock_path, 12345, time.time() - 5)

        lock = DatabaseLock(lock_path, wait_timeout=0.3, holder_inspector=insp)
        monkeypatch.setattr(lock, "_terminate_holder", lambda pid: False)
        with pytest.raises(LockBusyError, match="не удалось завершить"):
            lock.acquire()
        # fail-closed: чужой lock не тронут
        assert lock_path.exists()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == 12345


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


# ─── Кейс 6: termination race ──────────────────────────────────

class TestTerminationRace:
    def test_fresh_owner_not_stolen_during_steal(self, tmp_path, monkeypatch):
        """Lock пересоздан другим процессом до unlink — чужой свежий lock
        не удаляется (fail-closed), несмотря на подтверждённый ORPHAN."""
        chain = [(999_999_998, "python.exe", True), (77777, "?", False)]
        insp = FakeInspector(alive=True, create_time=time.time() - 5, chain=chain)
        lock = DatabaseLock(tmp_path / ".write_lock", wait_timeout=0.2,
                             holder_inspector=insp)
        monkeypatch.setattr(lock, "_terminate_holder", lambda pid: True)

        started_old = time.time() - 5
        _write_lock(tmp_path / ".write_lock", 999_999_998, started_old)

        # Первый вызов _read_holder — ORPHAN-holder; второй (после terminate,
        # перед unlink) — lock уже пересоздан ДРУГИМ процессом.
        calls = {"n": 0}

        def _fake_read():
            calls["n"] += 1
            if calls["n"] == 1:
                return {"pid": 999_999_998, "started": started_old}
            return {"pid": 424_242, "started": time.time()}  # свежий владелец

        monkeypatch.setattr(lock, "_read_holder", _fake_read)

        try:
            with pytest.raises(LockBusyError, match="пересоздан другим процессом"):
                lock.acquire()
            # чужой lock не удалён (файл на диске не тронут — данные прежние)
            assert (tmp_path / ".write_lock").exists()
            data = json.loads((tmp_path / ".write_lock").read_text(encoding="utf-8"))
            assert data["pid"] == 999_999_998
            assert not lock.is_held()
        finally:
            pass


# ─── Кейс 7: stale lock ────────────────────────────────────────

class TestStaleLock:
    def test_dead_pid_stolen_immediately(self, tmp_path):
        insp = FakeInspector(alive=False)
        lock_path = tmp_path / ".write_lock"
        _write_lock(lock_path, DEAD_PID, time.time() - 3600)

        lock = DatabaseLock(lock_path, wait_timeout=0.3, holder_inspector=insp)
        t0 = time.monotonic()
        lock.acquire()  # не должен ждать
        elapsed = time.monotonic() - t0
        try:
            assert lock.is_held()
            assert elapsed < 0.2, f"steal занял {elapsed:.2f}s — ждал зря"
        finally:
            lock.release()


# ─── Live-тест: реальная TerminateProcess (Windows) ────────────

class TestLiveTerminateWindows:
    @pytest.mark.skipif(sys.platform != "win32", reason="TerminateProcess — Windows-only")
    def test_real_orphan_process_terminated_and_stolen(self, tmp_path):
        """Реальный дочерний процесс + реальный TerminateProcess.

        Инжектор: реальный is_alive/create_time (WindowsProcessInspector),
        но parent_chain фейковый (корень мёртв) → ORPHAN.
        """
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

            class LiveOrphanInspector(WindowsProcessInspector):
                def parent_chain(self, pid, max_levels=8):
                    return [(pid, "python.exe", True), (77777, "?", False)]

            lock = DatabaseLock(lock_path, wait_timeout=0.3,
                                holder_inspector=LiveOrphanInspector())
            t0 = time.monotonic()
            lock.acquire()
            elapsed = time.monotonic() - t0
            try:
                assert lock.is_held()
                assert elapsed < 3.0, f"terminate+steal занял {elapsed:.2f}s"
            finally:
                lock.release()
            # дочерний процесс реально убит
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
