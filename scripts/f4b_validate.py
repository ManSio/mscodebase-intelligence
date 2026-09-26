#!/usr/bin/env python3
"""F4b result validator.

For every run_*.txt under results/f4b/<condition>/<model>/ it checks:
  - parses to exactly 14 numbered rows (`| # | entry |`);
  - every entry is a KNOWN catalogue slug or NONE (no hallucinated names);
  - no TIMEOUT / error / apology markers;
  - must-hit controls (3, 8, 13) match their expected entry;
  - must-none controls (5, 10, 14) are NONE.
It prints a per-run line and a summary, and exits non-zero on any anomaly.

`--selftest` feeds a deliberately broken sample and expects FAIL (negative
control: the validator must be able to fail).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "experiments" / "4A_unit_of_return" / "results" / "f4b"
ROW = re.compile(r"\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|")
ERROR_MARKERS = ("[TIMEOUT", "I need the handout", "Error:", "traceback")

ENTRIES = {
    "a-component-that-needs-starting-passes-every-behaviour-test",
    "a-guard-keyed-on-a-field-nobody-fills-is-a-silent-no-op",
    "a-surviving-mutant-can-mean-the-code-is-dead",
    "a-check-written-with-the-code-inherits-its-assumptions",
    "a-control-built-from-the-treated-arm-is-not-a-control",
    "one-calibration-pair-is-a-smoke-test-not-a-validation",
    "testing-rejection-is-not-testing-immutability",
    "a-benchmark-arm-is-its-candidate-pool",
    "a-failed-lookup-must-not-render-as-a-real-zero",
    "a-rate-knob-cannot-fix-a-denominator",
    "a-single-run-ranking-is-noise-even-at-temp-zero",
    "an-instrument-that-answers-a-different-question-can-be-wrong-two-ways",
    "a-cached-429-is-not-a-rate-limit",
    "a-number-that-moves-without-new-data-is-an-assumption",
    "a-generated-document-is-unverified-until-you-render-it",
    "an-instrument-that-reshapes-input-fabricates-the-test",
}
MUST_HIT = {3: "a-cached-429-is-not-a-rate-limit",
            8: "a-rate-knob-cannot-fix-a-denominator",
            13: "a-single-run-ranking-is-noise-even-at-temp-zero"}
MUST_NONE = [5, 10, 14]
NITEMS = 14


def check_text(name: str, raw: str) -> tuple[bool, str]:
    low = raw.lower()
    for m in ERROR_MARKERS:
        if m.lower() in low:
            return False, f"error-marker '{m}'"
    m = {int(a): b.strip() for a, b in ROW.findall(raw)}
    if len(m) != NITEMS:
        return False, f"parsed {len(m)}/{NITEMS} rows"
    bad = [f"#{k}={v}" for k, v in m.items()
           if v != "NONE" and v not in ENTRIES]
    if bad:
        return False, "unknown entry: " + "; ".join(bad)
    miss = [f"hit{k}->{m.get(k)}" for k, v in MUST_HIT.items() if m.get(k) != v]
    nn = [f"none{i}->{m.get(i)}" for i in MUST_NONE if m.get(i) != "NONE"]
    controls = "6/6" if not miss and not nn else "FAIL[" + ",".join(miss + nn) + "]"
    return (not miss and not nn), f"rows=14 controls={controls} #16=n/a"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        broken = ("I need the handout. Please paste the numbered items and the "
                  "index.\n| # | entry |\n|---|---|\n| 1 | a-made-up-entry |\n")
        ok, why = check_text("selftest", broken)
        print(f"selftest broken -> valid={ok} ({why})")
        good = "| # | entry |\n" + "".join(
            f"| {i} | NONE |\n" for i in range(1, NITEMS + 1))
        ok2, why2 = check_text("selftest2", good)
        print(f"selftest generic -> valid={ok2} ({why2})")
        return 0 if (not ok and ok2) else 1

    files = sorted(ROOT.rglob("run_*.txt"))
    if not files:
        print("no runs yet under", ROOT)
        return 0
    bad = 0
    for f in files:
        ok, why = check_text(f.name, f.read_text(encoding="utf-8", errors="replace"))
        rel = f.relative_to(ROOT).as_posix()
        print(f"{'OK ' if ok else 'BAD'} {rel}: {why}")
        bad += 0 if ok else 1
    print(f"\nfiles={len(files)} invalid={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - top-level guard reports and exits non-zero
        import traceback
        traceback.print_exc()
        raise SystemExit(2)
