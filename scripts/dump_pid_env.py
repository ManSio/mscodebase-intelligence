"""Дамп environment variables запущенного PID через /proc (Windows через wmic fallback)."""
import os
import sys
import subprocess

# Используем Win32 API через ctypes
import ctypes
from ctypes import wintypes

pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
if pid == 0:
    print("Usage: dump_pid_env.py <pid>")
    sys.exit(1)

print(f"Dumping environment for PID {pid}")

# Через wmic
result = subprocess.run(
    ["wmic", "process", f"where", f"ProcessId={pid}", "get", "ProcessId,CommandLine", "/format:list"],
    capture_output=True, text=True, timeout=10
)
print("--- wmic output ---")
print(result.stdout)
print("--- stderr ---")
print(result.stderr)
