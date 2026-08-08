"""Эксперимент C: симуляция зомби-holder'а PID-lock (осиротевший процесс).

Процесс-holder: захватывает DatabaseLock на tmp-путь, держит 60s.
Запускается DETACHED, чтобы его родитель умер сразу -> holder остаётся
живым процессом с мёртвым parent'ом (Windows не убивает детей).

Использование:
    python orphan_holder.py <lock_path>
"""
import json
import sys
import time
from pathlib import Path

from src.core.indexing.database_lock import DatabaseLock

lock_path = Path(sys.argv[1])
lock = DatabaseLock(lock_path)
lock.acquire()
print(json.dumps({"pid": __import__("os").getpid(), "lock": str(lock_path)}), flush=True)
time.sleep(600)
lock.release()
