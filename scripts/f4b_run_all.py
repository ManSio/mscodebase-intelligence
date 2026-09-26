#!/usr/bin/env python3
"""F4b orchestrator: run both conditions x 3 models, sequentially, with a log.

Launched detached (background). Progress is printed to stdout (redirected by
the launcher to a log file). Results land in
experiments/4A_unit_of_return/results/f4b/<condition>/.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "scripts" / "f4_blind_run.py"
FROZEN = REPO / "experiments" / "4A_unit_of_return" / "frozen" / "f4b"
RESULTS = REPO / "experiments" / "4A_unit_of_return" / "results" / "f4b"

PLAN = [
    ("symptom", "handout_symptom.md"),
    ("arrival", "handout_arrival.md"),
]
MODELS = [("longcat-2.0", 5), ("qwen3.7-plus", 3), ("deepseek-v4.1-flash", 3)]


def main() -> int:
    for cond, handout in PLAN:
        outdir = RESULTS / cond
        outdir.mkdir(parents=True, exist_ok=True)
        for model, runs in MODELS:
            cmd = [sys.executable, str(RUNNER),
                   "--model", f"opencode-go/{model}", "--variant", "high",
                   "--runs", str(runs), "--handout", str(FROZEN / handout),
                   "--outdir", str(outdir), "--timeout", "900"]
            t0 = time.time()
            print(f"[{time.strftime('%H:%M:%S')}] START {cond} {model} x{runs}", flush=True)
            p = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            dt = time.time() - t0
            print(f"[{time.strftime('%H:%M:%S')}] DONE  {cond} {model} in {dt:.0f}s "
                  f"rc={p.returncode}\n{p.stdout}{p.stderr}", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] ALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
