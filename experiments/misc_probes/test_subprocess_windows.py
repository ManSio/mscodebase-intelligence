"""
Эксперимент: тестирование subprocess на Windows Python 3.14.3
Запуск: python experiments/test_subprocess_windows.py
"""
import subprocess
import asyncio
import time
import sys
import os
from pathlib import Path


def find_git():
    git = os.environ.get('GIT_PYTHON_GIT_EXECUTABLE') or 'git'
    try:
        r = subprocess.run([git, '--version'], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return git
    except FileNotFoundError:
        pass
    # Fallback paths
    for p in [
        r'C:\Program Files\Git\bin\git.exe',
        r'C:\Program Files (x86)\Git\bin\git.exe',
        r'C:\Program Files\Git\cmd\git.exe',
    ]:
        if Path(p).exists():
            return p
    return None


def test_sync_run(git, label, **kwargs):
    """sync def + subprocess.run"""
    t0 = time.perf_counter()
    try:
        r = subprocess.run([git, '--version'], **kwargs)
        dt = (time.perf_counter() - t0) * 1000
        out = (r.stdout or '').strip()[:80]
        return f"  ✅ {label}: {out} ({dt:.0f}ms)"
    except Exception as e:
        return f"  ❌ {label}: {type(e).__name__}: {e}"


def test_sync_popen(git, label):
    """sync def + subprocess.Popen + communicate"""
    t0 = time.perf_counter()
    try:
        p = subprocess.Popen([git, '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate(timeout=10)
        dt = (time.perf_counter() - t0) * 1000
        return f"  ✅ {label}: {out.decode('utf-8', errors='replace').strip()[:80]} ({dt:.0f}ms)"
    except Exception as e:
        return f"  ❌ {label}: {type(e).__name__}: {e}"


def test_os_popen(git, label):
    """sync def + os.popen"""
    t0 = time.perf_counter()
    try:
        with os.popen(f'"{git}" --version') as f:
            out = f.read()
        dt = (time.perf_counter() - t0) * 1000
        return f"  ✅ {label}: {out.strip()[:80]} ({dt:.0f}ms)"
    except Exception as e:
        return f"  ❌ {label}: {type(e).__name__}: {e}"


async def test_async_create_subprocess(git, label):
    """async def + asyncio.create_subprocess_exec"""
    t0 = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            git, '--version',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        dt = (time.perf_counter() - t0) * 1000
        return f"  ✅ {label}: {stdout.decode('utf-8', errors='replace').strip()[:80]} ({dt:.0f}ms)"
    except Exception as e:
        return f"  ❌ {label}: {type(e).__name__}: {e}"


async def test_async_to_thread(git, label):
    """async def + asyncio.to_thread + subprocess.run"""
    t0 = time.perf_counter()
    try:
        r = await asyncio.to_thread(
            subprocess.run,
            [git, '--version'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=10,
        )
        dt = (time.perf_counter() - t0) * 1000
        return f"  ✅ {label}: {(r.stdout or '').strip()[:80]} ({dt:.0f}ms)"
    except Exception as e:
        return f"  ❌ {label}: {type(e).__name__}: {e}"


async def main():
    print("=" * 65)
    print("🔬 ЭКСПЕРИМЕНТ: subprocess на Windows")
    print(f"   Python: {sys.version}")
    print(f"   Event loop: {asyncio.get_event_loop_policy().__class__.__name__}")
    print("=" * 65)

    git = find_git()
    if not git:
        print("\n❌ Git не найден! Установите Git для Windows.")
        sys.exit(1)
    print(f"📌 git: {git}\n")

    # ─── СИНХРОННЫЕ ТЕСТЫ ───
    print("【Sync】subprocess.run с PIPE:")
    print(test_sync_run(git, "capture_output=True", capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10))

    print("【Sync】subprocess.run с текстовыми потоками:")
    print(test_sync_run(git, "stdout=PIPE, text=True", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', timeout=10))

    print("【Sync】subprocess.run с байтовыми PIPE:")
    print(test_sync_run(git, "stdout=PIPE", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10))

    print("【Sync】subprocess.run с DEVNULL (без PIPE):")
    print(test_sync_run(git, "DEVNULL", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10))

    print("【Sync】subprocess.Popen + communicate (PIPE):")
    print(test_sync_popen(git, "Popen + PIPE"))

    print("【Sync】os.popen:")
    print(test_os_popen(git, "os.popen"))

    # ─── АСИНХРОННЫЕ ТЕСТЫ ───
    print("\n【Async】asyncio.create_subprocess_exec (PIPE):")
    print(await test_async_create_subprocess(git, "create_subprocess_exec"))

    print("【Async】asyncio.to_thread + subprocess.run:")
    print(await test_async_to_thread(git, "to_thread + subprocess.run"))

    print("=" * 65)
    print("🏁 Эксперимент завершён")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
