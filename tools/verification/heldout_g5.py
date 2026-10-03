"""Held-out for G5. EVERY case runs against a TEMP COPY — the real manifest is
never written to.

Why the redesign (this file went through three broken versions):
  v1 wrote the mutated manifest over the tracked file and restored it in `finally`.
     A crash mid-write left a 0-byte manifest, and the gate then reported
     "MANIFEST UNREADABLE" — indistinguishable from a real defect.
  v2 snapshotted the on-disk file as the baseline, so a defect left by a previous
     run was baked into the "pristine" copy.
  v3 sabotaged the gate source IN PLACE. Its `finally` restored the sabotaged text,
     leaving a 0-byte g5_denominator.py.

All three share one cause: mutating state that outlives the test. The fix is
structural — each case gets its own directory, and nothing shared is touched.

Three properties are asserted, per §19.3:
  1. each injected defect is blocked for its OWN stated reason
  2. a sabotaged gate MISSES the same defect (the harness can fail)
  3. the real gate blocks it again (the sabotage did not leak)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROJECTS_ROOT = REPO.parent
MAN_NAME = "denominator_manifest.json"
GATE_NAME = "g5_denominator.py"


def build_baseline() -> bytes:
    """Regenerate the manifest from the live tree. DERIVED, never read from disk:
    a file left dirty by an earlier run must not become the 'pristine' fixture."""
    p = subprocess.run([sys.executable, "-B", str(HERE / "bootstrap_denominator_manifest.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    if p.returncode != 0:
        print("BASELINE REGENERATION FAILED — refusing to test against an unknown fixture")
        print((p.stdout or "") + (p.stderr or ""))
        sys.exit(2)
    data = (HERE / MAN_NAME).read_bytes()
    if not data.strip():
        print("BASELINE IS EMPTY — refusing to run (19.6/T10: no metric over no input)")
        sys.exit(2)
    return data


def run_gate(dirpath: Path) -> tuple[int, str]:
    # MSCB_REPO_ROOT points the copy at the real checkout: the copy lives in a temp
    # dir, so its parents[2] is an empty folder and every scope profile would fail.
    env = dict(os.environ,
               MSCB_PROJECTS_ROOT=str(PROJECTS_ROOT),
               MSCB_REPO_ROOT=str(REPO))
    p = subprocess.run([sys.executable, "-B", str(dirpath / GATE_NAME)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def scenario(baseline: bytes, mutate=None, sabotage: bool = False) -> tuple[int, str]:
    """A scenario gets its own directory: manifest + gate, nothing else."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copy(HERE / GATE_NAME, d / GATE_NAME)
        data = json.loads(baseline.decode("utf-8-sig"))
        if mutate:
            mutate(data)
        (d / MAN_NAME).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        if sabotage:
            src = (d / GATE_NAME).read_text(encoding="utf-8")
            broken = src.replace("    return blocks, stats",
                                 "    return [], stats  # SABOTAGE: never block")
            if broken == src:
                return -1, "SABOTAGE DID NOT APPLY (anchor line missing)"
            (d / GATE_NAME).write_text(broken, encoding="utf-8")
        return run_gate(d)


# --- mutators: each touches a DISTINCT artifact, so exactly one reason can fire ---
def m_understate(d):
    d["artifacts"]["repo/WISDOM.md"]["n_sig1"] = 1


def m_overstate_reviewed(d):
    d["artifacts"]["repo/ISSUE.md"]["n_reviewed"] = 10**6


def m_drop_artifact(d):
    d["artifacts"].pop("repo/EXPERIMENTS_LOG.md")


def m_bad_exempt(d):
    d["artifacts"]["repo/AGENT_DIARY.md"].update(
        {"reason_code": "EXEMPT", "exempt_code": "TRUST_ME"})


def m_class_drift(d):
    # repo/KNOWN_ISSUES.md is class INTERNAL in the manifest; flip it to PUBLIC.
    # It used to be a portfolio artifact, which is out of scope under the repo_only
    # profile a bare clone gets — mutating it was a no-op there, so the case passed
    # vacuously with rc=0 where a block was required.
    d["artifacts"]["repo/KNOWN_ISSUES.md"]["class"] = "PUBLIC"


CASES = [
    ("understated count (real growth)", m_understate, 3, "UNREGISTERED GROWTH"),
    ("n_reviewed inflated", m_overstate_reviewed, 3, "REVIEWED EXCEEDS FOUND"),
    ("artifact silently dropped", m_drop_artifact, 3, "UNREGISTERED ARTIFACT"),
    ("free-text exempt reason", m_bad_exempt, 3, "UNKNOWN CODE"),
    ("class boundary moved", m_class_drift, 3, "CLASS DRIFT"),
]


def main() -> int:
    baseline = build_baseline()
    results: list[bool] = []

    print("=" * 92)
    print(f"G5 HELD-OUT — {len(CASES)} injected defects, each in its own temp directory")
    print("=" * 92)
    for name, mut, want_rc, needle in CASES:
        rc, out = scenario(baseline, mut)
        ok = rc == want_rc and needle in out
        results.append(ok)
        print(f"  [{'OK ' if ok else 'XX '}] {name:34} rc={rc} (want {want_rc})")
        if not ok:
            for line in out.strip().splitlines():
                if line.startswith("  [x]") or "FATAL" in line or "UNDETERMIN" in line:
                    print(f"        {line.strip()[:100]}")

    # control: the pristine manifest must pass, with no defect anywhere
    rc, out = scenario(baseline)
    ok = rc == 0
    results.append(ok)
    print(f"  [{'OK ' if ok else 'XX '}] {'pristine manifest passes':34} rc={rc} (want 0)")

    # falsifiability: the harness must be able to fail
    rc, out = scenario(baseline, m_understate, sabotage=True)
    ok = rc == 0 and "UNREGISTERED GROWTH" not in out
    results.append(ok)
    print(f"  [{'OK ' if ok else 'XX '}] {'sabotaged gate MISSES the defect':34} rc={rc} (want 0)")
    if not ok:
        print(f"        sabotage output: {out.strip()[:100]}")

    # and the real gate must still block it
    rc, out = scenario(baseline, m_understate)
    ok = rc == 3 and "UNREGISTERED GROWTH" in out
    results.append(ok)
    print(f"  [{'OK ' if ok else 'XX '}] {'real gate blocks it again':34} rc={rc} (want 3)")

    # the real manifest must be untouched by this whole run
    after = (HERE / MAN_NAME).read_bytes()
    ok = after == baseline
    results.append(ok)
    print(f"  [{'OK ' if ok else 'XX '}] {'real manifest unchanged':34} "
          f"({len(after)} bytes)")

    print("=" * 92)
    bad = results.count(False)
    if bad:
        print(f"HELD-OUT FAILED: {bad} of {len(results)}")
        return 1
    print(f"HELD-OUT PASSED — {len(results)}/{len(results)}: each defect blocked for its own reason")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
