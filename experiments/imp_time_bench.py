"""E2 — стоимость холодного импорта модулей MCP-слоя (2026-08-17).

Методика: N прогонов в ОТДЕЛЬНЫХ процессах (свежий sys.modules), медиана.
Контрольная группа: до и после прототипа (E3) — та же команда, тот же python.

Запуск: python experiments/imp_time_bench.py [--runs N] [modules...]
"""

from __future__ import annotations

import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

DEFAULT_MODULES = [
    "src.mcp.tools.indexing_tools",
    "src.mcp.tools.meta_tools",
    "src.mcp.server",
    "src.core.project_resolution",
]


def main() -> int:
    args = sys.argv[1:]
    runs = 7
    if args and args[0] == "--runs":
        runs = int(args[1])
        args = args[2:]
    mods = args or DEFAULT_MODULES

    for mod in mods:
        times = []
        for _ in range(runs):
            t0 = time.perf_counter()
            r = subprocess.run(
                [sys.executable, "-c", f"import {mod}"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(REPO),
            )
            dt = (time.perf_counter() - t0) * 1000
            times.append(dt)
            if r.returncode != 0:
                print(f"{mod}: IMPORT FAIL: {(r.stderr or '').strip().splitlines()[-1][:120]}")
                times = None
                break
        if times:
            print(f"{mod}: median={statistics.median(times):.1f}ms  "
                  f"min={min(times):.1f}ms  max={max(times):.1f}ms  (n={runs}, свежий процесс)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)