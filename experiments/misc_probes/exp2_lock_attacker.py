"""EXPERIMENT 2 (attacker): живой holder с мёртвым родителем убивается текущим кодом.

Сценарий 1-в-1 с инцидентом 2026-08-26:
1. launcher-процесс (аналог venvwlauncher) спавнит holder (аналог живого MCP другого окна)
   с DETACHED_PROCESS и ЗАВЕРШАЕТСЯ → у holder'а родитель мёртв.
2. attacker (мы, аналог второго окна) вызывает DatabaseLock.acquire() на тот же lock.
   Текущий код: classify_holder → parent_chain=[holder alive, launcher dead] → ORPHAN
   → TerminateProcess(holder) → lock stolen.
   Ожидаемое правильное поведение: LockBusyError, holder жив (fail-closed).

Usage:
    venv/Scripts/python.exe experiments/misc_probes/exp2_lock_attacker.py <lock_path> <holder_hold_sec>
"""

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.indexing.database_lock import (  # noqa: E402
    DatabaseLock,
    LockBusyError,
    WindowsProcessInspector,
)

HOLDER = Path(__file__).resolve().parent / "exp2_lock_holder.py"
LAUNCHER = (
    "import subprocess,sys;"
    "subprocess.Popen([sys.executable, r'%s', r'%s', '%s'],"
    " creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NO_WINDOW)"
)


def main() -> int:
    lock_path = Path(sys.argv[1])
    hold_sec = float(sys.argv[2])
    lock_path.unlink(missing_ok=True)

    # 1. Launcher спавнит holder и выходит (родитель holder'а = launcher, мёртв).
    launcher_code = LAUNCHER % (HOLDER, lock_path, hold_sec)
    subprocess.run(
        [sys.executable, "-c", launcher_code],
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    time.sleep(1.2)  # holder успел взять lock
    print(f"[attacker] lock exists={lock_path.exists()}", flush=True)

    # 2. Находим holder'а: процесс, держащий lock (по содержимому файла).
    holder_pid = None
    for _ in range(20):
        try:
            import json

            data = json.loads(lock_path.read_text(encoding="utf-8"))
            holder_pid = data.get("pid")
            if holder_pid:
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    print(f"[attacker] holder pid={holder_pid}", flush=True)
    if not holder_pid:
        print("VERDICT: holder not found — abort")
        return 2

    insp = WindowsProcessInspector()
    chain = insp.parent_chain(holder_pid, max_levels=8)
    print(f"[attacker] holder alive={insp.is_alive(holder_pid)} parent-chain={chain}", flush=True)

    # 3. Атакуем (второй процесс пытается захватить тот же lock).
    lock = DatabaseLock(lock_path, wait_timeout=2.0, poll_interval=0.2)
    try:
        lock.acquire()
        outcome = "ACQUIRED (stolen!)"
    except LockBusyError as exc:
        outcome = f"LockBusyError (fail-closed): {exc}"
    except RuntimeError as exc:
        outcome = f"RuntimeError: {exc}"

    holder_alive = insp.is_alive(holder_pid) if holder_pid else False
    print(f"[attacker] outcome: {outcome}", flush=True)
    print(f"[attacker] holder_alive_after_attempt={holder_alive}", flush=True)

    # cleanup: убиваем holder если жив (это НЕ реальный MCP, а тестовый процесс)
    if holder_alive:
        try:
            holder = __import__("ctypes").windll.kernel32
            handle = holder.OpenProcess(0x0001, False, holder_pid)
            if handle:
                holder.TerminateProcess(handle, 1)
                holder.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            pass
    lock_path.unlink(missing_ok=True)
    if holder_alive:
        print("VERDICT: holder survived — FAIL-CLOSED OK", flush=True)
        return 0
    print("VERDICT: holder killed — BUG REPRODUCED", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())