"""Проверка: кого именно содержит lock и кого убивает TerminateProcess
в venv-цепочке (venvlauncher 20888 -> python 7936)."""

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
    LockHolderState,
    WindowsProcessInspector,
)

TMP = BASE / "experiments" / "lock_zombie" / "probe_tmp"
TMP.mkdir(parents=True, exist_ok=True)
lock_path = TMP / ".write_lock"

spawner = BASE / "experiments" / "lock_zombie" / "spawn_orphan.py"
env = dict(os.environ, PYTHONPATH=str(BASE))
subprocess.run([sys.executable, str(spawner)], env=env, cwd=str(BASE), check=True, timeout=30)
time.sleep(2)

data = json.loads(lock_path.read_text(encoding="utf-8"))
holder_pid = data["pid"]
print(f"lock holder pid={holder_pid}")

insp = WindowsProcessInspector()
print(f"holder alive={insp.is_alive(holder_pid)} create_time={insp.create_time(holder_pid):.0f} "
      f"started={data['started']:.0f}")
chain = insp.parent_chain(holder_pid)
print("chain:", chain)

lock = DatabaseLock(lock_path)
state = lock.classify_holder(holder_pid, data["started"])
print("classify:", state)

if state is LockHolderState.ORPHAN:
    ok = lock._terminate_holder(holder_pid)
    print(f"terminate(holder {holder_pid}) -> {ok}")
    time.sleep(1)
    print(f"holder alive after terminate: {insp.is_alive(holder_pid)}")

# остались ли живые python-процессы от этой цепочки?
import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402
from src.core.indexing.database_lock import DatabaseLock as DL  # noqa: E402

print("venv-python alive in chain:", [
    (p, DL._is_pid_alive(p)) for p in [holder_pid, chain[1][0]] if chain and len(chain) > 1
])
