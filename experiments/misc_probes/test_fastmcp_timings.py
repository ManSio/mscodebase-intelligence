"""
Тест: сколько может длиться инструмент в FastMCP на Windows Python 3.14.
Запуск напрямую (имитация MCP вызова).
"""
import asyncio
import subprocess
import time
import sys
from pathlib import Path


async def simulate_mcp_call(name: str, coro):
    """Имитирует вызов MCP инструмента и замеряет время"""
    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=30)
        dt = (time.perf_counter() - t0) * 1000
        status = "✅"
        result_short = str(result)[:60]
    except asyncio.TimeoutError:
        dt = 30000
        status = "❌ TIMEOUT"
        result_short = "asyncio.TimeoutError"
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000
        status = "❌"
        result_short = f"{type(e).__name__}: {e}"

    print(f"  {status} {name}: {dt:.0f}ms → {result_short}")


async def main():
    print(f"Python: {sys.version}")
    print()

    # 1. Быстрый subprocess.run (git --version)
    print("【Sync subprocess.run】")
    await simulate_mcp_call("git --version (capture_output)", 
        asyncio.to_thread(
            lambda: subprocess.run(
                ['git', '--version'],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=15,
            )
        )
    )

    # 2. subprocess.run с capture_output
    print("\n【subprocess.run - git log -5】")
    await simulate_mcp_call("git log -5 --oneline (capture_output=True)",
        asyncio.to_thread(
            lambda: subprocess.run(
                ['git', 'log', '-5', '--oneline'],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=15,
            )
        )
    )

    # 3. subprocess.run с DEVNULL
    print("\n【subprocess.run - DEVNULL】")
    await simulate_mcp_call("git log -5 (DEVNULL)",
        asyncio.to_thread(
            lambda: subprocess.run(
                ['git', 'log', '-5'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=15,
            )
        )
    )

    # 4. Простой sleep (имитация долгого инструмента)
    print("\n【asyncio.sleep】")
    for sec in [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]:
        await simulate_mcp_call(f"sleep {sec}s",
            asyncio.sleep(sec))

    # 5. Sync time.sleep в to_thread
    print("\n【sync time.sleep в to_thread】")
    for sec in [0.1, 0.5, 1.0, 2.0]:
        await simulate_mcp_call(f"time.sleep({sec}) в to_thread",
            asyncio.to_thread(time.sleep, sec))


if __name__ == "__main__":
    asyncio.run(main())
