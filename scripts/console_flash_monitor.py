#!/usr/bin/env python
"""console_flash_monitor.py — ловит, КТО и КОГДА спавнит консольные процессы.

Инцидент 2026-08-14: на Windows при работе MCP (pythonw, без консоли) любой
console-subsystem дочерний процесс (git/powershell/wmic/netstat/cmd/bash/wsl)
БЕЗ CREATE_NO_WINDOW создаёт своё видимое окно-«мигалку». Этот монитор
поллит создание процессов и пишет в лог: время | имя | PID | родительская
цепочка (до 4 уровней) | командная строка. Запускать фоном и просто
работать/ждать — он поймает виновника с точной атрибуцией.

Usage:
    python scripts/console_flash_monitor.py [--seconds 180] [--interval 0.3]

Лог: <MSCODEBASE_DATA_DIR>/logs/console_flash.log (или рядом с скриптом).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Классы процессов, которые показывают окно консоли (мигалки)
_CONSOLE_TYPES = frozenset({
    "cmd.exe", "conhost.exe", "powershell.exe", "pwsh.exe", "git.exe",
    "wmic.exe", "netstat.exe", "bash.exe", "sh.exe", "wsl.exe",
    "taskkill.exe", "curl.exe", "python.exe", "llama-server.exe",
    "node.exe", "npm.exe",
})

_LOG_FILE = "console_flash.log"


def _log_path() -> Path:
    """Лог в data_root/logs (вне репозитория — §0.6)."""
    try:
        from src.core.artifact_paths import get_data_root
        return get_data_root(Path(".")) / "logs" / _LOG_FILE
    except Exception:
        import tempfile
        return Path(tempfile.gettempdir()) / _LOG_FILE


def _snapshot() -> dict[int, dict]:
    """Все процессы: pid -> {ppid, name, cmdline}."""
    table: dict[int, dict] = {}
    try:
        # Toolhelp32 — быстрее WMI, не требует powershell
        kernel32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return table

        class _PE32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_char * 260),
            ]

        entry = _PE32()
        entry.dwSize = ctypes.sizeof(_PE32)
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = {
                "ppid": entry.th32ParentProcessID,
                "name": entry.szExeFile.decode("ascii", "replace").lower(),
            }
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
        kernel32.CloseHandle(snapshot)
    except Exception:
        pass
    return table


def _parent_chain(pid: int, table: dict[int, dict], depth: int = 4) -> str:
    chain = []
    cur = pid
    for _ in range(depth):
        info = table.get(cur)
        if info is None:
            chain.append(f"{cur}(?)")
            break
        chain.append(f"{cur}({info['name']})")
        if info["ppid"] == cur or info["ppid"] == 0:
            break
        cur = info["ppid"]
    return " <- ".join(chain)


def main() -> int:
    ap = argparse.ArgumentParser(description="Ловит создание консольных процессов")
    ap.add_argument("--seconds", type=float, default=180.0, help="сколько секунд наблюдать")
    ap.add_argument("--interval", type=float, default=0.3, help="шаг опроса, сек")
    args = ap.parse_args()

    logf = _log_path()
    logf.parent.mkdir(parents=True, exist_ok=True)
    seen: set[int] = set()
    deadline = time.time() + args.seconds
    hits: list[dict] = []

    print(f"📡 Монитор консольных процессов: {args.seconds}s, шаг {args.interval}s")
    print(f"   Лог: {logf}")

    prev = _snapshot()
    seen.update(prev.keys())
    while time.time() < deadline:
        cur = _snapshot()
        for pid, info in cur.items():
            if pid in seen:
                continue
            seen.add(pid)
            if info["name"] not in _CONSOLE_TYPES:
                continue
            record = {
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "name": info["name"],
                "pid": pid,
                "parent_chain": _parent_chain(info["ppid"], cur),
                "cmdline": "",
            }
            try:
                import subprocess
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                record["cmdline"] = out.decode("utf-8", "replace").strip()[:200]
            except Exception:
                pass
            hits.append(record)
            line = (f"[{record['time']}] {record['name']} PID={record['pid']} "
                    f"PARENT: {record['parent_chain']}")
            if record["cmdline"]:
                line += f" | CMD: {record['cmdline']}"
            print("🟨", line)
            with open(logf, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        prev = cur
        time.sleep(max(0.05, args.interval))

    print(f"\n📊 Итог: {len(hits)} консольных процессов за {args.seconds}s")
    by_parent: dict[str, int] = {}
    for h in hits:
        pchain = h["parent_chain"]
        by_parent[pchain] = by_parent.get(pchain, 0) + 1
    for chain, cnt in sorted(by_parent.items(), key=lambda x: -x[1])[:10]:
        print(f"  {cnt}x  {chain}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⏹ Остановлено.")
        sys.exit(0)
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
