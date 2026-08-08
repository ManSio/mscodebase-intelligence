"""Launcher: spawn-ит holder'а как сироту (DETACHED) и сразу выходит.

Родитель holder'а = этот launcher. После его выхода holder остаётся
живым процессом с мёртвым parent'ом — симуляция зомби-инстанса MCP.

Usage: spawn_orphan.py [lock_path]
"""
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(r"D:\Project\MSCodeBase")
lock_path = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "experiments" / "lock_zombie" / "test_db" / ".write_lock"
lock_path.parent.mkdir(parents=True, exist_ok=True)

py = sys.executable
holder = BASE / "experiments" / "lock_zombie" / "orphan_holder.py"
flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
env = dict(os.environ, PYTHONPATH=str(BASE))
proc = subprocess.Popen(
    [py, str(holder), str(lock_path)],
    cwd=str(BASE),
    env=env,
    creationflags=flags,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(f"holder spawned: pid={proc.pid}, launcher exits now", flush=True)
sys.exit(0)
