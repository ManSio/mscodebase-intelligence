"""Проверка сигналов зомби-детекции для holder'а lock-файла.

Читает .write_lock, проверяет 3 сигнала:
1. holder PID жив?
2. parent holder'а жив? (если parent мёртв -> holder осиротел = зомби)
3. create_time holder'а vs started в lock (PID-reuse / фейковый lock)

Windows-only (ctypes, без psutil — psutil не установлен в venv).
"""
import json
import sys
import time
from ctypes import wintypes
import ctypes

kernel32 = ctypes.windll.kernel32


def pid_alive(pid: int) -> bool:
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok) and code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def parent_pid(pid: int):
    """ParentProcessId через Toolhelp32Snapshot (без psutil)."""
    TH32CS_SNAPPROCESS = 0x00000002
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == -1:
        return None
    try:
        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            if entry.th32ProcessID == pid:
                return entry.th32ParentProcessID
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
        return None
    finally:
        kernel32.CloseHandle(snapshot)


def main() -> int:
    lock_path = sys.argv[1]
    data = json.loads(open(lock_path, encoding="utf-8").read())
    pid = data["pid"]
    started = data.get("started", 0)
    holder_alive = pid_alive(pid)
    ppid = parent_pid(pid) if holder_alive else None
    parent_alive = pid_alive(ppid) if ppid is not None else None

    print(f"holder pid={pid} alive={holder_alive}")
    if holder_alive:
        print(f"holder parent pid={ppid} parent_alive={parent_alive}")
        # create_time holder'а через GetProcessTimes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h:
            class FT(ctypes.Structure):
                _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]
            create, exit_, kern, user = FT(), FT(), FT(), FT()
            if kernel32.GetProcessTimes(h, ctypes.byref(create), ctypes.byref(exit_),
                                        ctypes.byref(kern), ctypes.byref(user)):
                ft = (create.dwHighDateTime << 32) | create.dwLowDateTime
                # FILETIME (100ns since 1601) -> unix seconds
                unix = ft / 10_000_000 - 11644473600
                print(f"holder create_time={unix:.0f} lock.started={started:.0f} "
                      f"delta={unix - started:+.0f}s")
                print(f"PID-reuse detect (|delta|>5): {abs(unix - started) > 5}")
            kernel32.CloseHandle(h)

        verdict = []
        if parent_alive is False:
            verdict.append("ORPHAN: parent dead -> steal safe")
        elif parent_alive is True:
            verdict.append("parent alive -> likely healthy, wait")
        else:
            verdict.append("parent unknown (no access)")
        print("VERDICT:", "; ".join(verdict))
    else:
        print("VERDICT: holder dead -> stale, steal safe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
