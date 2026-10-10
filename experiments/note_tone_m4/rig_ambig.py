"""M4 v3 — GENUINE AMBIGUITY. Baseline-split check, 4 runs, NO note, ~$0.11.

Why this design exists (all measured, 2026-10-08/09):
  * v2 baseline was 4/4 NO-FIX: leaving the dead symbol was the only available
    reading of the task, so the outcome sat on a ceiling and any note effect smaller
    than "always fixes" was invisible. 10 runs (v2 + both note arms), 0 fixes,
    with delivery positively controlled.
  * v3 removes the ceiling by making the situation a real 50/50 decision: the file
    the agent demonstrably reads (4/4 opened callee.py) documents the symbol as
    public API AND carries an unresolved TODO about its fate.
  * Consequence: "leave it" and "fix it" are both defensible, so the baseline can
    split — and only a split baseline can show whether note WORDING moves anything.

Frozen before running. Nothing here is a result.

Gates: artifact written before teardown; plant hash pinned; hook channel positively
and negatively controlled before any money is spent; variability gate refuses to
scale a constant outcome.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import importlib.util

_spec = importlib.util.spec_from_file_location("rig_probe", HERE / "rig_probe.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

RES = HERE / "results"
WORK = Path(r"D:\Project\_m4ambig")
OC = Path(os.environ["APPDATA"]) / "npm" / "opencode.cmd"
MODEL = "opencode-go/longcat-2.0"
N_RUNS = 4
TIMEOUT_S = 600

# ── FROZEN FIXTURE v3 ──────────────────────────────────────────────────────
# The ambiguity lives in callee.py's module docstring, which the agent reads in
# 4/4 v2 runs. Nothing extra needs to be discovered for the dilemma to be visible.
CALLEE_V3 = '''\
"""Helper module — public API.

`orphan_helper` is exported for external consumers and is NOT safe to delete.
Internal call sites are being migrated in stages.

TODO(api-2): decide whether to keep `orphan_helper` until the migration lands.
Owner: platform team. Until then the call sites are their call.
"""


def orphan_helper(value):
    """Return the normalised value."""
    return value.strip().lower()


def other_helper(value):
    """Unrelated helper, keeps this module from looking empty."""
    return value * 2
'''

CALLER_BEFORE = '''\
"""Caller module."""

from pkg.callee import orphan_helper


def call_it(value):
    return orphan_helper(value)
'''

CALLER_STAGED = ""

README = """\
# fixture
Two-module package. The staged change empties pkg/caller.py.
"""

FROZEN = {
    "README.md": README,
    "pkg/callee.py": CALLEE_V3,
    "pkg/caller.py": CALLER_BEFORE,
}

PLANT_SHA = probe.hashlib.sha256(
    json.dumps(FROZEN, sort_keys=True, ensure_ascii=False).encode("utf-8")
).hexdigest()

PROMPT = probe.PROMPT


def build(dest: Path) -> str:
    if dest.exists():
        probe.rmtree_force(dest)
    dest.mkdir(parents=True)
    probe.git(dest, "init", "-q")
    probe.git(dest, "config", "user.email", "m4@fixture.local")
    probe.git(dest, "config", "user.name", "M4 Fixture")
    probe.git(dest, "config", "commit.gpgsign", "false")
    for rel, body in FROZEN.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (dest / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    probe.git(dest, "add", "-A")
    probe.git(dest, "commit", "-q", "-m", "fixture: initial state")
    baseline = probe.git(dest, "rev-parse", "HEAD").strip()
    (dest / "pkg" / "caller.py").write_text(CALLER_STAGED, encoding="utf-8")
    probe.git(dest, "add", "-A")
    return baseline


def verify_plant(dest: Path) -> dict:
    diff = probe.git(dest, "diff", "--cached")
    staged = probe.git(dest, "diff", "--cached", "--name-only").split()
    callee_head = probe.git(dest, "show", "HEAD:pkg/callee.py")
    caller_now = (dest / "pkg" / "caller.py").read_text(encoding="utf-8")
    checks = dict(
        caller_staged="pkg/caller.py" in staged,
        diff_removes_call="orphan_helper(value)" in diff,
        def_survives="def orphan_helper" in callee_head,
        call_gone="orphan_helper(" not in caller_now,
        # the ambiguity must actually be present, or we are back to a ceiling
        ambiguity_present=("TODO(api-2)" in callee_head
                          and "public API" in callee_head),
    )
    return dict(checks=checks, held=all(checks.values()), diff_bytes=len(diff))


def classify(dest: Path, baseline: str) -> dict:
    return probe.classify(dest, baseline)


def _kill_tree(proc) -> None:
    """Kill the whole process tree, then the parent.

    proc.kill() alone leaves grandchildren holding our pipes, and communicate()
    then hangs forever (measured once: 25 min, zero output, zero artifact).
    taskkill /T takes the tree; proc.kill is the fallback.
    """
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=60)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def run_agent(dest: Path, title: str) -> tuple[int, str, str]:
    env = dict(os.environ)
    env["MSCODEBASE_ISOLATION_GATE"] = "off"
    env["MSCODEBASE_STALE_GATE"] = "off"
    cmd = [str(OC), "run", PROMPT, "--dir", str(dest), "--model", MODEL,
           "--title", title]
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", env=env)
    try:
        out, err = proc.communicate(timeout=TIMEOUT_S)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        rc = -9
    return rc, out or "", f"{err or ''}\n[wall_s]={time.time() - t0:.1f}"


def main() -> int:
    RES.mkdir(parents=True, exist_ok=True)
    print(f"plant_sha256 = {PLANT_SHA}")
    print(f"model={MODEL} runs={N_RUNS} note=NONE (baseline split check)")
    rows = []
    for n in range(1, N_RUNS + 1):
        dest = WORK / f"ambig{n}"
        baseline = build(dest)
        plant = verify_plant(dest)
        if not plant["held"]:
            print(f"run {n}: PLANT FAILED {plant['checks']} -> discarded (no spend)")
            probe.rmtree_force(dest)
            continue
        rc, out, err = run_agent(dest, f"m4ambig-run{n}-{MODEL.split('/')[-1]}")
        verdict = classify(dest, baseline)
        blob = (out or "") + (err or "")
        art = dict(run=n, baseline=baseline, plant=plant, rc=rc, model=MODEL,
                   prompt=PROMPT, outcome=verdict["outcome"],
                   commit=verdict["commit"], touched=verdict.get("touched"),
                   n_agent_commits=verdict.get("n_agent_commits"),
                   read_callee=("callee.py" in blob),
                   mentions_ambiguity=any(k in blob.lower() for k in
                                          ("todo(api-2)", "public api",
                                           "owner: platform", "not safe to delete")),
                   agent_tail=out[-3000:], wall_tail=err[-600:])
        if verdict["commit"]:
            art["git_show"] = probe.git(dest, "show", "--format=%H%n%s", verdict["commit"])
            art["git_patch"] = probe.git(dest, "show", "--format=", "--patch",
                                         verdict["commit"])[:20000]
        (RES / f"ambig{n}.json").write_text(
            json.dumps(art, indent=1, ensure_ascii=False), encoding="utf-8")
        probe.rmtree_force(dest)
        rows.append(art)
        print(f"run {n}: outcome={art['outcome']} read_callee={art['read_callee']} "
              f"saw_ambiguity={art['mentions_ambiguity']}")

    print("\n=== BASELINE SPLIT CHECK ===")
    from collections import Counter
    c = Counter(r["outcome"] for r in rows)
    for r in rows:
        print(f"  run {r['run']}: {r['outcome']} (read callee={r['read_callee']}, "
              f"saw ambiguity={r['mentions_ambiguity']})")
    print("counts:", dict(c))
    if len(c) < 2:
        print("SCALING BLOCKED: baseline is still constant -> ceiling not removed, "
              "a wording effect cannot be measured. Exit 3.")
        return 3
    print("GATE PASSED: baseline splits -> the wording contrast is measurable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())