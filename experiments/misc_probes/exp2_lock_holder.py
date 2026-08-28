"""EXPERIMENT 2 — живой holder с мёртвым родителем: текущий DatabaseLock УБИВАЕТ его.

Воспроизводит сценарий инцидента 2026-08-26 (PID 20052 killed by 12524):
1. holder.py (этот файл, вызванный как дочерний процесс) захватывает lock и живёт N сек.
2. Родитель выходит → у holder'а parent chain: [[holder, alive], [ppid, DEAD/missing]]
   (ровно как venvwlauncher-цепочка реального MCP).
3. attacker.py вызывает DatabaseLock.acquire() на тот же lock.
   Текущий код: classify_holder → ORPHAN → TerminateProcess(holder) → stolen.
   Ожидаемое правильное поведение: LockBusyError, holder жив.

Запуск: venv/Scripts/python.exe attacker.py <lock_path> <holder_exit_after_sec>

Usage (from holder):
    venv/Scripts/python.exe experiments/misc_probes/exp2_lock_holder.py <lock_path> <hold_sec>
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.indexing.database_lock import DatabaseLock  # noqa: E402


def main() -> int:
    lock_path = Path(sys.argv[1])
    hold_sec = float(sys.argv[2])
    lock = DatabaseLock(lock_path)
    lock.acquire()
    print(f"[holder pid={os.getpid()}] lock acquired, holding {hold_sec}s", flush=True)
    time.sleep(hold_sec)
    lock.release()
    print(f"[holder pid={os.getpid()}] released", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())