"""
Тест: имитация вызова FastMCP sync vs async с subprocess.
Запуск: Python experiments/test_fastmcp_direct.py
"""
import asyncio
import subprocess
import time
import sys


def sync_fn():
    """Имитация sync инструмента FastMCP"""
    t0 = time.perf_counter()
    r = subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=10)
    dt = (time.perf_counter() - t0) * 1000
    return f"sync: {r.stdout.strip()} ({dt:.0f}ms)"


async def async_fn():
    """Имитация async инструмента FastMCP"""
    t0 = time.perf_counter()
    r = subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=10)
    dt = (time.perf_counter() - t0) * 1000
    return f"async: {r.stdout.strip()} ({dt:.0f}ms)"


async def async_with_to_thread():
    """Имитация async + to_thread"""
    t0 = time.perf_counter()
    r = await asyncio.to_thread(
        subprocess.run,
        ['git', '--version'], capture_output=True, text=True, timeout=10)
    dt = (time.perf_counter() - t0) * 1000
    return f"async+to_thread: {r.stdout.strip()} ({dt:.0f}ms)"


async def main():
    print(f"Python: {sys.version}")
    print(f"Loop: {asyncio.get_event_loop_policy().__class__.__name__}")
    print()

    # 1. Sync прямо (как FastMCP делает)
    print("1. Sync напрямую (блокирует event loop):")
    t0 = time.perf_counter()
    result = sync_fn()
    dt = (time.perf_counter() - t0) * 1000
    print(f"   {result} (всего {dt:.0f}ms)")

    # 2. Async с subprocess.run (блокирует event loop)
    print("2. Async + subprocess.run (блокирует event loop):")
    t0 = time.perf_counter()
    result = await async_fn()
    dt = (time.perf_counter() - t0) * 1000
    print(f"   {result} (всего {dt:.0f}ms)")

    # 3. Async + to_thread
    print("3. Async + asyncio.to_thread:")
    t0 = time.perf_counter()
    result = await async_with_to_thread()
    dt = (time.perf_counter() - t0) * 1000
    print(f"   {result} (всего {dt:.0f}ms)")

    # 4. Async + create_subprocess_exec
    print("4. Async + create_subprocess_exec:")
    t0 = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        'git', '--version',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    dt = (time.perf_counter() - t0) * 1000
    print(f"   {stdout.decode().strip()} ({dt:.0f}ms)")


asyncio.run(main())
