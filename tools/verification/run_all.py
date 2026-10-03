"""run_all.py вЂ” one command that proves every guard in the agent system can fail.

Runs, in order:
  1. knowledge organ validator   (rc 1 on findings, selftest proves checks fail)
  2. gates selftest              (rc 1 if any gate cannot block)
  3. gates held-out validation   (rc 1 if a gate waves a KNOWN defect through)
  4. protocol guard (project)    (rc 1 on findings, selftest proves checks fail)

Rule this enforces: a guard exists only if it can fail AND it fails on things that
are actually broken. Three of the four assertions below were FALSE when first
written and were caught by this runner, not by review.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

# tools/verification/run_all.py -> parents[2] is the repo root, so a clone at any
# path runs the same suite. Verified by existence check, not by counting:
#   parents[0]=tools/verification  parents[1]=tools  parents[2]=<repo root>
# Getting this wrong makes every repo-relative step look like a missing file, which
# is indistinguishable from a real missing dependency unless the gate distinguishes them.
REPO = pathlib.Path(__file__).resolve().parents[2]
# The knowledge registries live INSIDE the repo now (tools/knowledge/), so their
# references resolve against the same checkout being verified. Running them from
# ~/.config kept them in one tree while the paths they named lived in another,
# and every branch switch dangled half the references.
KNOWLEDGE = pathlib.Path(__file__).resolve().parents[1] / "knowledge" / "check_knowledge.py"
# The pitfalls skill is personal and stays outside the repo; K3 is skipped when absent.
CFG = pathlib.Path(os.environ.get("OPENCODE_CFG", pathlib.Path.home() / ".config" / "opencode"))
HAVE_KNOWLEDGE = KNOWLEDGE.exists()
# The gates live NEXT TO this script, inside the repo, so they version with the code
# they audit. This is the whole point of the move: a guard that is not committed
# does not exist for CI or for anyone else.
G = pathlib.Path(__file__).resolve().parent
PY = sys.executable

STEPS = [
    ("knowledge: registries resolve", [PY, str(KNOWLEDGE)], 0),
    ("knowledge: checks can fail", [PY, str(KNOWLEDGE), "--selftest"], 0),
    ("gates: can block", [PY, str(G / "gates.py"), "--selftest"], 0),
    ("gates: block known defects (held-out)", [PY, str(G / "heldout_validation.py")], 0),
    ("G5 denominator: can block", [PY, str(G / "g5_denominator.py"), "--selftest"], 0),
    ("G5 denominator: blocks real defects (held-out)", [PY, str(G / "heldout_g5.py")], 0),
    ("gates: each blocks for its OWN reason (RT6)", [PY, str(G / "heldout_rt6_reasons.py")], 0),
    ("gates: scope + decisive region declared (RT8)", [PY, str(G / "heldout_rt8_scope.py")], 0),
    ("G2: publishable-number controls", [PY, str(G / "heldout_g2_publishable.py")], 0),
    ("G5 denominator: no unregistered numbers", [PY, str(G / "g5_denominator.py")], 0),
    # Benchmark decay guard: the badge and the census in README/WISDOM were 42, 118,
    # 6 and 827 tests out of date respectively. Both were published numbers a reader
    # could cite. The selftest proves the comparison can reject in BOTH directions —
    # a one-sided `live <= stated` check passed an inflated badge and was caught here.
    ("claims: check can reject both directions", [PY, str(G / "verify_public_claims.py"), "--selftest"], 0),
    ("claims: published numbers reproduce today", [PY, str(G / "verify_public_claims.py")], 0),
    ("suite: portable, no author-absolute paths", [PY, str(G / "heldout_relocation.py")], 0),
    # The command files (.opencode/command/) cite these exact invocations. If the CLI
    # changes shape, the commands become prose that cannot be run, which is worse than
    # having no command at all.
    ("CLI: every documented invocation works", [PY, str(G / "heldout_cli_contract.py")], 0),
    ("protocol guards: can fail", [PY, str(REPO / "scripts" / "audit_protocol_guards.py"), "--selftest"], 0),
]

# Steps that SURFACE findings without deciding pass/fail. Marking a noisy guard as a gate
# is worse than not gating: a red CI on untriaged noise trains everyone to ignore red.
# Per §19.5 the guard may not be published as a verdict until its false-positive share is
# measured — so this is reported as an open measurement, not silently passed and not failed.
# FP share MEASURED 2026-10-03 by scripts/triage_protocol_findings.py: 8 reported,
# 5 false positives = 62.5%, 3 actionable. The number is surfaced WITH its false-positive
# share; quoting "8 findings" alone would overstate the defects by 2.7x.
SURFACE = [
    ("protocol guards: findings (FP share measured: 62.5% of 8 reported)",
     [PY, str(REPO / "scripts" / "audit_protocol_guards.py")]),
]


def main() -> int:
    print("=" * 78)
    print("AGENT GUARD SUITE вЂ” every guard must be able to fail")
    print("=" * 78)
    failed = []
    for name, cmd, expect in STEPS:
        if name.startswith("knowledge") and not HAVE_KNOWLEDGE:
            print(f"[SKIP] {name:44} knowledge validator not found: {KNOWLEDGE}")
            print("       Reported as skipped, not passed. A step that did not run is not a green step.")
            continue
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600)
        ok = p.returncode == expect
        # print the verdict line only, not the whole report
        tail = [x for x in (p.stdout or "").strip().splitlines() if x.strip()]
        last = tail[-1][:88] if tail else (p.stderr or "").strip().splitlines()[-1:][0][:88] if p.stderr else ""
        print(f"[{'OK ' if ok else 'BAD'}] {name:44} rc={p.returncode} (want {expect})  {last}")
        if not ok:
            failed.append(name)
            for line in (p.stdout or "").strip().splitlines()[-12:]:
                print(f"        {line[:110]}")

    print("-" * 78)
    for name, cmd in SURFACE:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600)
        out = (p.stdout or "").strip()
        m = [x for x in out.splitlines() if "finding" in x.lower() and ":" in x]
        n = m[-1].split(":", 1)[1].strip() if m else "?"
        print(f"[OPEN] {name:52} {n}")
        print("       FP share measured 62.5% (5 of 8 were noise) -> 3 actionable.")
        print("       Quoting the raw finding count as 'N problems' overstates defects by 2.7x (§19.5).")

    print("=" * 78)
    if failed:
        print(f"GUARD SUITE: {len(failed)} provability step(s) FAILED -> {failed}")
        return 1
    print("GUARD SUITE: every guard is provable (can fail) and its own selftest passes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
