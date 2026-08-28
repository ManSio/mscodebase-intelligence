"""PROBE 3 — атака: поддельный lock с чужим живым PID (explorer.exe).

Атакующий (тот же user, другой процесс) пишет lock-файл с pid системного
процесса explorer.exe + started=прошлое. Что вернёт КЛАССИФИКАЦИЯ (без kill)?
Если ORPHAN — DatabaseLock ТЕРМИНИРУЕТ explorer.exe (kill произвольного
процесса по поддельному lock).

Безопасно: только classify_holder(), TerminateProcess не вызывается.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.indexing.database_lock import (  # noqa: E402
    DatabaseLock,
    LockHolderState,
)


def main() -> int:
    target_pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if not target_pid:
        print("usage: probe3_fake_lock_foreign_pid.py <pid> [lock_path]")
        return 2

    lock_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(sys.argv[2] if len(sys.argv) > 2 else f"{Path.home()}/fake_lock_test.lock")
    lock_path.unlink(missing_ok=True)

    # Атакующий пишет lock на чужой живой PID со «старым» started.
    fake = {"pid": target_pid, "started": time.time() - 3600, "role": "worker"}
    lock_path.write_text(json.dumps(fake), encoding="utf-8")

    lock = DatabaseLock(lock_path, wait_timeout=0.5, poll_interval=0.1)
    state = lock.classify_holder(target_pid, fake["started"], holder_data=fake)
    print(f"[probe3] pid={target_pid}: classify_holder -> {state.value}")
    if state.value == "healthy":
        print("[probe3] FIXED: живой процесс HELD (wait), TerminateProcess удалён")
    elif state.value == "ambiguous":
        print("[probe3] safe: непроверяемый holder → fail-closed wait")
    return 0


if __name__ == "__main__":
    sys.exit(main())