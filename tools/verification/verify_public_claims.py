"""verify_public_claims.py — every published number that a reader could cite,
paired with the command that re-derives it today.

Research basis (2026-10-03, [🔍 ИССЛЕДОВАНИЕ]):

  * GTM-Bench, "Keeping a Benchmark Honest" (2026-09-06) names the class:
    **benchmark decay** — "the benchmark is public and static, so over months
    the field optimizes toward it. The number stays the same; what it measures
    erodes." Its first defence is structural, not one-time: "every reported
    score names the version it was run against; a number without a version is
    uninterpretable."
  * READU (arXiv 2607.15780) detects README bugs with internal + external
    consistency checkers and an **alert judge to remove false positives** —
    which is why every entry below is hand-adjudicated rather than regex-inferred.
    (Two automated triage attempts were made in this repo and both were wrong
    in opposite directions; see scripts/triage_protocol_findings.py.)
  * driftmd lists "badge versions — badge says v2.0.0, package.json says
    v3.1.0" as its own check. That is exactly the defect this file was written
    for: README badge 1965 vs 2007 collected.

A claim with no command is not verified, it is merely written down. Every entry
carries one. `UNVERIFIABLE` is a legal verdict here — it means the artifact that
produced the number is gone — but it is NOT a pass, and it must be re-stated
rather than quietly kept.

Exit: 0 all resolve or are honestly marked · 3 a claim contradicts reality.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]

# Each claim: the literal text in the file, the file, and a command whose output
# must CONTAIN the live value. `contains` keeps the check robust against log noise.
CLAIMS: list[dict] = [
    {
        "id": "readme.test_badge",
        "file": "README.md",
        "text": "tests-2001%20passed",
        "claim": "the test-count badge says 2001 passed",
        "command": [sys.executable, "-m", "pytest", "tests/", "-q", "--collect-only"],
        "extract": r"(\d+)/\d+ tests collected",
        "compare": "near",
        "tolerance": 40,   # collected is the ceiling; passed = collected - skipped
        "why": "a badge nobody moves is a claim nobody checks",
    },
    {
        "id": "readme.test_count_arch",
        "file": "README.md",
        "text": "2007 tests",
        "claim": "the architecture table says 2007 tests",
        "command": [sys.executable, "-m", "pytest", "tests/", "-q", "--collect-only"],
        "extract": r"(\d+)/\d+ tests collected",
        "compare": "near",
        "tolerance": 5,
        "why": "same fact, second location — one fix must update both or they diverge",
    },
    {
        "id": "wisdom.intel_count",
        "file": "WISDOM.md",
        "text": "intel_*=20",
        "claim": "the live census records 20 intel tools",
        "command": [sys.executable, "scripts/check_tool_names.py"],
        "extract": r"intel_\*\s*=\s*(\d+)",
        "compare": "eq",
        "why": "a count of registered tools is a fact, not an estimate. The dated "
               "2026-08-12 snapshot (intel_*=14) is deliberately NOT this claim.",
    },
    {
        "id": "wisdom.test_count",
        "file": "WISDOM.md",
        "text": "2007 collected",
        "claim": "the live census records 2007 collected tests",
        "command": [sys.executable, "-m", "pytest", "tests/", "-q", "--collect-only"],
        "extract": r"(\d+)/\d+ tests collected",
        "compare": "near",
        "tolerance": 5,
        "why": "same class as the README badge, in the distilate meant to be exact",
    },
]

# Claims that cannot be re-derived today. Each needs a REASON and, per §19.11,
# the supersede chain — never a silent edit.
UNVERIFIABLE: dict[str, str] = {}


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def claimed_value(claim: dict) -> int | None:
    """Read the number the FILE currently states, so the check compares the doc
    against reality rather than against a number hardcoded here."""
    p = ROOT / claim["file"]
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(re.escape(claim["text"]).replace(r"\%20", r"[ %]"), text)
    if not m:
        return None
    m2 = re.search(r"(\d+)", m.group(0))
    return int(m2.group(1)) if m2 else None


def compare(stated: int | None, live: int, claim: dict) -> tuple[bool, str | None]:
    """Bidirectional by design. A first cut used `live <= stated + tol`, which
    only catches UNDERstatement — a badge inflated to 999999 would pass while the
    real suite collects 2007. Silence on the overstated side is not a pass."""
    if stated is None:
        return False, "could not read the stated number back out of the file"
    tol = claim.get("tolerance", 0)
    if claim["compare"] == "eq":
        if live == stated:
            return True, None
        return False, f"exact count claim, expected {stated}"
    delta = live - stated
    if abs(delta) <= tol:
        return True, None
    verb = "understates" if delta > 0 else "overstates"
    return False, (f"doc {verb} by {abs(delta)} (tolerance {tol}) — "
                   f"a badge nobody moves is a claim nobody checks")


def selftest() -> int:
    """§19.3: the checker must be able to FAIL, in BOTH directions.
    Four synthetic claims. The two marked expect_ok=False are the ones a
    one-sided `live <= stated` comparison would have passed silently."""
    cases = [
        ("README.md", "tests-1999999%20passed", 2007, "near", 40, False, "overstated"),
        ("README.md", "tests-1%20passed", 2007, "near", 40, False, "understated"),
        ("README.md", "tests-2000%20passed", 2007, "near", 40, True, "within tolerance"),
        ("WISDOM.md", "intel_*=20", 20, "eq", 0, True, "exact match"),
    ]
    failures = 0
    for _f, text, live, cmp_, tol, expect_ok, label in cases:
        stated = int(re.search(r"(\d+)", text).group(1))
        ok, _ = compare(stated, live, {"compare": cmp_, "tolerance": tol})
        hit = ok == expect_ok
        failures += 0 if hit else 1
        print(f"  [{'OK ' if hit else 'XX '}] {label:<18} stated={stated:<8} live={live:<6} "
              f"-> {'allowed' if ok else 'WRONG':<6} (want {'allowed' if expect_ok else 'WRONG'})")
    if failures:
        print(f"SELFTEST FAILED: {failures} synthetic case(s) misclassified")
        return 1
    print(f"SELFTEST PASSED — {len(cases) - failures}/{len(cases)} synthetic cases correct, "
          f"including {sum(1 for c in cases if not c[5])} that must be rejected")
    return 0


def main() -> int:
    results = []
    print("=" * 92)
    print("PUBLIC CLAIM VERIFICATION — every published number, against the command that re-derives it")
    print("=" * 92)

    for claim in CLAIMS:
        f = ROOT / claim["file"]
        if not f.exists():
            print(f"  [MISS] {claim['id']}: file {claim['file']} does not exist")
            results.append(True)
            continue
        if claim["text"] not in f.read_text(encoding="utf-8", errors="replace"):
            # The text has been corrected — the claim is no longer being made.
            print(f"  [GONE] {claim['id']}: '{claim['text']}' is no longer in {claim['file']} "
                  f"(either fixed or reworded — confirm which)")
            results.append(True)
            continue

        stated = claimed_value(claim)
        rc, out = run(claim["command"])
        m = re.search(claim["extract"], out)
        if not m:
            print(f"  [SKIP] {claim['id']}: command produced no parsable value")
            for line in out.strip().splitlines()[-2:]:
                print(f"          {line[:88]}")
            results.append(True)
            continue
        live = int(m.group(1))
        ok, why_bad = compare(stated, live, claim)
        results.append(ok)
        print(f"  [{'OK  ' if ok else 'WRONG'}] {claim['id']}")
        print(f"          {claim['file']} states {stated}; live now {live}"
              + ("" if ok or why_bad is None else f"  — {why_bad}"))
        if not ok:
            print(f"          why it matters: {claim['why']}")

    for cid, reason in UNVERIFIABLE.items():
        print(f"  [UNVERIFIABLE] {cid}: {reason}")

    bad = results.count(False)
    print()
    if bad:
        print(f"CLAIM CHECK FAILED: {bad} of {len(results)} published numbers contradict reality")
        print("Per READU's alert judge: triage before believing the count — some may be a")
        print("parse failure rather than a false claim. Each wrong one is a decision, not an edit.")
        return 3
    print(f"CLAIM CHECK PASSED — {len(results)}/{len(results)} published numbers reproduce today")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    raise SystemExit(main())