"""Бенчмарк WS9: measured before/after для self-healing PID-lock.

Кейсы:
1. healthy-holder  — наш процесс держит lock; второй acquire → LockBusyError;
2. orphan-holder   — реальный осиротевший процесс держит lock; acquire
                     детектит ORPHAN → TerminateProcess → steal;
3. stale-holder    — мёртвый PID в lock → steal;
4. free            — свободный lock → acquire.

Замеры печатаются в stdout (ms). Скрипт не меняет прод-БД — использует
tmp-пути. Требует Windows (TerminateProcess / Toolhelp32) для orphan-кейса.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(r"D:\Project\MSCodeBase")
sys.path.insert(0, str(BASE))

from src.core.indexing.database_lock import (  # noqa: E402
    DatabaseLock,
    LockBusyError,
)

TMP = BASE / "experiments" / "lock_zombie" / "bench_tmp"


def _bench(name, fn):
    t0 = time.perf_counter()
    result = fn()
    ms = (time.perf_counter() - t0) * 1000
    print(f"[{name}] {ms:.0f} ms | {result}")
    return ms


def case_healthy():
    path = TMP / "healthy" / ".write_lock"
    lock1 = DatabaseLock(path)
    lock1.acquire()
    try:
        def _run():
            lock2 = DatabaseLock(path, wait_timeout=1.5, poll_interval=0.05)
            try:
                lock2.acquire()
                return "UNEXPECTED-ACQUIRED"
            except LockBusyError as e:
                return f"LockBusyError: {str(e)[:60]}"
        return _bench("healthy-holder (wait=1.5s)", _run)
    finally:
        lock1.release()


def case_orphan():
    path = TMP / "orphan" / ".write_lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    spawner = BASE / "experiments" / "lock_zombie" / "spawn_orphan.py"
    env = dict(os.environ, PYTHONPATH=str(BASE))
    subprocess.run([sys.executable, str(spawner), str(path)], env=env,
                   cwd=str(BASE), check=True, timeout=30)
    time.sleep(2)  # holder успел записать lock

    def _run():
        lock = DatabaseLock(path)  # дефолтный inspector (Windows)
        lock.acquire()
        return f"acquired pid={os.getpid()}"
    ms = _bench("orphan-holder (terminate+steal)", _run)
    # cleanup: lock уже наш — release
    DatabaseLock(path).release()
    return ms


def case_stale():
    path = TMP / "stale" / ".write_lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": 999_999_999, "started": time.time() - 3600,
                                "role": "worker"}), encoding="utf-8")

    def _run():
        lock = DatabaseLock(path)
        lock.acquire()
        lock.release()
        return "steal ok"
    return _bench("stale-holder (dead pid)", _run)


def case_free():
    path = TMP / "free" / ".write_lock"

    def _run():
        lock = DatabaseLock(path)
        lock.acquire()
        lock.release()
        return "acquire ok"
    return _bench("free (no contention)", _run)


if __name__ == "__main__":
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    case_free()
    case_stale()
    case_healthy()
    if sys.platform == "win32":
        case_orphan()
    else:
        print("[orphan-holder] SKIPPED (не Windows)")
    shutil.rmtree(TMP, ignore_errors=True)
    print("BENCH_DONE")
