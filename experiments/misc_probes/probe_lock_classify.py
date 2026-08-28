"""PROBE: classify real live MCP processes with the real WindowsProcessInspector.

Reproduces the false-positive ORPHAN decision of DatabaseLock.classify_holder
against the CURRENTLY RUNNING MCP servers (multi-window), the same way the
killer instance (PID 12524) classified the victim (PID 20052) at 19:42:52.

Usage:
    venv/Scripts/python.exe experiments/misc_probes/probe_lock_classify.py <pid> [pid...]
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.indexing.database_lock import (  # noqa: E402
    LockHolderState,
    WindowsProcessInspector,
)


def dump_chain(chain):
    if not chain:
        return None
    return " <-".join(
        f" {pid}:{name}[{'alive' if alive else 'dead'}]" for pid, name, alive in chain
    )


def main(pids):
    insp = WindowsProcessInspector()
    print(f"{'PID':>8} {'alive':>5}  {'decision':<10} parent-chain")
    print("-" * 100)
    for pid in pids:
        alive = insp.is_alive(pid)
        chain = insp.parent_chain(pid, max_levels=8)
        ct = insp.create_time(pid)
        # Честный holder: lock-файл записан ПОСЛЕ создания процесса.
        started = (ct + 5.0) if ct else (time.time() + 5.0)
        # Реплика решения classify_holder (строки 413-438 database_lock.py):
        if not alive:
            decision = LockHolderState.DEAD
        elif pid == os.getpid():
            decision = LockHolderState.HEALTHY
        elif ct is not None and ct > started + 2.0:
            decision = LockHolderState.DEAD
        else:
            # R3TF: живой PID с валидным create_time → HELD (wait), never kill
            decision = LockHolderState.HEALTHY
        print(f"{pid:>8} {str(alive):>5}  {decision.value:<10} {dump_chain(chain)}")
        if decision.value != "healthy":
            print(f"  note: {decision.value} — но TerminateProcess удалён (R3TF)")
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    pids = [int(p) for p in sys.argv[1:]]
    main(pids)