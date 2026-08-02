"""Тесты DatabaseLock — межпроцессный single-writer lock (Layer 3 defense).

Покрывают семантику, вынесенную из LanceDBManager._acquire_pid_lock
(P1-14 / P1-15 / INC-6C62): атомарный захват, ожидание живого владельца
с таймаутом, steal мёртвого/битого lock-а, гонку нескольких экземпляров.
Проверяется КОРРЕКТНОСТЬ результата (ровно один владелец, файл с верным
PID, отсутствие осиротевших lock-файлов), а не только отсутствие исключений
(§5.13 AGENTS.md).
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from src.core.indexing.database_lock import DatabaseLock

DEAD_PID = 999_999_999  # заведомо несуществующий PID (Windows/Unix)


@pytest.fixture
def lock_path(tmp_path):
    return tmp_path / "test_db" / ".write_lock"


class TestAcquireRelease:
    def test_acquire_creates_lock_file_with_pid(self, lock_path):
        lock = DatabaseLock(lock_path, wait_timeout=0.2)
        lock.acquire()
        try:
            assert lock.is_held() is True
            assert lock_path.exists()
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            assert data["pid"] == os.getpid()
            assert data["role"] == "worker"
        finally:
            lock.release()

    def test_release_removes_lock_file(self, lock_path):
        lock = DatabaseLock(lock_path, wait_timeout=0.2)
        lock.acquire()
        lock.release()
        assert lock.is_held() is False
        assert not lock_path.exists()

    def test_release_idempotent(self, lock_path):
        lock = DatabaseLock(lock_path, wait_timeout=0.2)
        lock.acquire()
        lock.release()
        lock.release()  # второй release не должен бросать исключений
        assert not lock_path.exists()

    def test_acquire_after_release_succeeds(self, lock_path):
        lock1 = DatabaseLock(lock_path, wait_timeout=0.2)
        lock1.acquire()
        lock1.release()
        lock2 = DatabaseLock(lock_path, wait_timeout=0.2)
        lock2.acquire()
        assert lock2.is_held() is True
        lock2.release()

    def test_context_manager_releases(self, lock_path):
        with DatabaseLock(lock_path, wait_timeout=0.2) as lock:
            assert lock.is_held() is True
            assert lock_path.exists()
        assert not lock_path.exists()

    def test_del_releases_lock(self, lock_path):
        lock = DatabaseLock(lock_path, wait_timeout=0.2)
        lock.acquire()
        del lock
        assert not lock_path.exists()


class TestContention:
    def test_double_acquire_live_holder_raises_after_timeout(self, lock_path):
        """Живой владелец (тот же процесс) — второй захват ждёт и падает."""
        lock1 = DatabaseLock(lock_path, wait_timeout=0.2, poll_interval=0.05)
        lock1.acquire()
        try:
            lock2 = DatabaseLock(lock_path, wait_timeout=0.2, poll_interval=0.05)
            with pytest.raises(RuntimeError, match="still held by alive pid"):
                lock2.acquire()
            # lock2 НЕ должен был снять чужой lock (никакого unlink чужого файла)
            assert lock1.is_held() is True
            assert lock_path.exists()
        finally:
            lock1.release()

    def test_steal_lock_with_dead_pid(self, lock_path):
        """Мёртвый PID владельца — lock забирается без ожидания."""
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps({"pid": DEAD_PID, "started": 0, "role": "worker"}),
            encoding="utf-8",
        )
        lock = DatabaseLock(lock_path, wait_timeout=0.2)
        lock.acquire()
        try:
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            assert data["pid"] == os.getpid()  # lock перезаписан нашим PID
        finally:
            lock.release()

    def test_steal_broken_lock_file(self, lock_path):
        """Битый (invalid JSON) lock — трактуется как stale и забирается."""
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("not-a-json{", encoding="utf-8")
        lock = DatabaseLock(lock_path, wait_timeout=0.2)
        lock.acquire()
        assert lock.is_held() is True
        lock.release()

    def test_race_exactly_one_winner(self, lock_path):
        """Гонка N=8 экземпляров на одном пути: ровно один владелец.

        Проверка корректности (§5.13): победитель ровно один, остальные
        получают RuntimeError, lock-файл после гонки содержит PID владельца.
        """
        n = 8
        results: list = []
        barrier = threading.Barrier(n)

        def _try_acquire():
            lock = DatabaseLock(lock_path, wait_timeout=0.3, poll_interval=0.05)
            barrier.wait()  # одновременный старт
            try:
                lock.acquire()
                results.append(("acquired", lock))
            except RuntimeError:
                results.append(("failed", None))
            except Exception as exc:  # noqa: BLE001 — тест фиксирует любой сбой
                results.append((f"unexpected:{type(exc).__name__}", None))

        threads = [threading.Thread(target=_try_acquire) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [r for r in results if r[0] == "acquired"]
        failed = [r for r in results if r[0] == "failed"]
        unexpected = [r for r in results if r[0].startswith("unexpected")]

        assert unexpected == [], f"Unexpected exceptions: {unexpected}"
        assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}"
        assert len(failed) == n - 1, f"Expected {n - 1} failures, got {len(failed)}"

        # Lock-файл принадлежит победителю (единственный процесс — наш PID).
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
        winners[0][1].release()
        assert not lock_path.exists()
