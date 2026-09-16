# -*- coding: utf-8 -*-
"""A1: sysmon (coverage run) overhead vs baseline — та же сессия, чередование.
Та же методика, что Exp 7 (198.6s trace vs 174.8s baseline).
Атаки: прогрев, чередование, min по 2 прогонам, capture returncode.
"""
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def run(cmd, tag, timeout=600):
    t0 = time.monotonic()
    p = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    rc = p.wait(timeout=timeout)
    dt = time.monotonic() - t0
    print(f"[{tag}] rc={rc} time={dt:.2f}s")
    if rc != 0:
        print(f"[{tag}] FAILED rc={rc} — прерываю серию")
    return rc, dt


def main():
    base = [PYTHON, "-m", "pytest", "tests/", "-q", "--no-header", "-p", "no:cacheprovider"]
    cov = [PYTHON, "-m", "coverage", "run", "--rcfile=.coveragerc", "-m", "pytest",
           "tests/", "-q", "--no-header", "-p", "no:cacheprovider"]

    print("=== A1: sysmon overhead A/B (та же сессия) ===")
    print("Warmup (file cache):")
    rc, _ = run(base, "warmup")
    if rc:
        return 1

    print("\nПрогоны (чередование, min по 2):")
    baseline, covs = [], []
    for i in (1, 2):
        _, tb = run(base, f"baseline[{i}]")
        baseline.append(tb)
        _, tc = run(cov, f"coverage[{i}]")
        covs.append(tc)

    min_b, min_c = min(baseline), min(covs)
    overhead = (min_c - min_b) / min_b * 100
    print(f"\n=== RESULTS ===")
    print(f"baseline: {baseline}")
    print(f"coverage: {covs}")
    print(f"min baseline = {min_b:.2f}s | min coverage = {min_c:.2f}s")
    print(f"overhead = {overhead:+.2f}%")
    print(f"exp7 reference: sys.settrace = +13.6% (198.6 vs 174.8)")

    return 0


if __name__ == "__main__":
    sys.exit(main())