"""zombie_probe — проверка «зомби-holder» через walk по цепочке родителей.

Вердикт по 2 сигналам:
1. holder жив?
2. Цепочка родителей holder'а (до N уровней) ведёт к ЖИВОМУ Zed.exe?
   - Живой Zed в цепочке  -> holder — рабочий MCP окна -> ждать (wait)
   - Корень цепочки мёртв  -> holder осиротел (зомби) -> steal safe

Также: create_time holder'а vs lock.started (PID-reuse/фейк).
Windows-only, без psutil (его нет в venv).
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


class PE32(ctypes.Structure):
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


def process_table():
    TH32CS_SNAPPROCESS = 0x00000002
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    out = {}
    if snapshot == -1:
        return out
    try:
        entry = PE32()
        entry.dwSize = ctypes.sizeof(PE32)
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            out[entry.th32ProcessID] = {
                "ppid": entry.th32ParentProcessID,
                "name": entry.szExeFile.decode("ascii", "replace"),
            }
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
        return out
    finally:
        kernel32.CloseHandle(snapshot)


def walk_chain(holder_pid: int, table: dict, max_levels: int = 8):
    chain = []
    cur = holder_pid
    for _ in range(max_levels):
        if cur is None or cur == 0:
            chain.append((cur, "-", "root(0)"))
            break
        info = table.get(cur)
        if info is None:
            # Мёртвые процессы отсутствуют в Toolhelp-снапшоте;
            # живость проверяем OpenProcess (надёжно, ловит PID-reuse).
            alive = pid_alive(cur)
            chain.append((cur, "?", "alive" if alive else "DEAD"))
            if not alive:
                break
            break
        alive = pid_alive(cur)
        chain.append((cur, info["name"], "alive" if alive else "DEAD"))
        if not alive:
            break
        cur = info["ppid"]
        if cur == holder_pid:
            break
    return chain


def main() -> int:
    lock_path = sys.argv[1]
    data = json.loads(open(lock_path, encoding="utf-8").read())
    pid = data["pid"]
    started = data.get("started", 0)
    table = process_table()

    holder_alive = pid_alive(pid)
    print(f"holder pid={pid} alive={holder_alive} role={data.get('role')}")
    if holder_alive:
        chain = walk_chain(pid, table)
        print("chain (child->root):")
        for lvl, (p, name, state) in enumerate(chain):
            print(f"  [{lvl}] pid={p} name={name} {state}")

        live_zed = any("Zed" in name for (_, name, state) in chain if state == "alive")
        root_dead = chain and chain[-1][2] in ("DEAD", "root(0)") and not live_zed
        direct_parent_alive = len(chain) > 1 and chain[1][2] == "alive"

        print(f"  direct_parent_alive={direct_parent_alive}")
        print(f"  live_Zed_in_chain={live_zed}")
        print(f"  chain_root_dead={root_dead}")
        if live_zed:
            print("VERDICT: HEALTHY (живое окно Zed в цепочке) -> WAIT")
        elif root_dead:
            print("VERDICT: ORPHAN/ZOMBIE (корень цепочки мёртв) -> STEAL safe")
        else:
            print("VERDICT: AMBIGUOUS (нет Zed, корень жив) -> WAIT (fail-closed)")
    else:
        print("VERDICT: STALE (holder мёртв) -> STEAL safe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
