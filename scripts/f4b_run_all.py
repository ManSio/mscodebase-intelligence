#!/usr/bin/env python3
"""F4b orchestrator (parallel): 2 conditions x 3 models = 6 independent streams.

Each stream (condition, model) runs its N repeats sequentially in its own
workdir; the six streams run concurrently. Results land in
experiments/4A_unit_of_return/results/f4b/<condition>/<model>/.
"""
from __future__ import annotations

import concurrent.futures as cf
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "scripts" / "f4_blind_run.py"
FROZEN = REPO / "experiments" / "4A_unit_of_return" / "frozen" / "f4b"
RESULTS = REPO / "experiments" / "4A_unit_of_return" / "results" / "f4b"

STREAMS = [
    (cond, handout, model, runs)
    for cond, handout in [("symptom", "handout_symptom.md"),
                          ("arrival", "handout_arrival.md")]
    for model, runs in [("longcat-2.0", 5), ("qwen3.7-plus", 3),
                        ("deepseek-v4.1-flash", 3)]
]


def run_stream(s: tuple) -> str:
    cond, handout, model, runs = s
    outdir = RESULTS / cond / model
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(RUNNER), "--model", f"opencode-go/{model}",
           "--variant", "high", "--runs", str(runs),
           "--handout", str(FROZEN / handout), "--outdir", str(outdir),
           "--timeout", "900"]
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] START {cond}/{model} x{runs}", flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    dt = time.time() - t0
    print(f"[{time.strftime('%H:%M:%S')}] DONE  {cond}/{model} in {dt:.0f}s "
          f"rc={p.returncode} | {p.stdout.strip()} {p.stderr.strip()}", flush=True)
    return f"{cond}/{model}"


def main() -> int:
    print(f"[{time.strftime('%H:%M:%S')}] launching {len(STREAMS)} streams", flush=True)
    with cf.ThreadPoolExecutor(max_workers=len(STREAMS)) as ex:
        for _ in ex.map(run_stream, STREAMS):
            pass
    print(f"[{time.strftime('%H:%M:%S')}] ALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
