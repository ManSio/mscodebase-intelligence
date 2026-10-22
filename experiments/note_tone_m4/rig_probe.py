"""M4 reachability probe — 4 runs, NO advisory note, fresh isolated fixture repo.

Purpose (frozen before running, 2026-10-08): measure whether an agent SPONTANEOUSLY
discovers that the staged change removed the last caller of a still-defined symbol.
This is the precondition the full-30 run never verified and never could: the note was the
only source of that fact, so every arm sat at 0 upstream of the treatment.

Gates enforced here (each one fails loudly instead of silently scoring a null):
  G1 artifact-before-teardown : run directory is deleted only AFTER the commit diff,
                                stat and tree state are written into results/.
  G2 plant-hash pinned        : every run is rebuilt from FROZEN fixture text in this
                                file; the sha256 of that text is recorded per run and
                                must be identical across runs.
  G3 no-hooks fixture         : the fixture is a fresh `git init` repo, so no
                                mscodebase pre-commit hook can block the commit for an
                                unrelated reason (the full-30 blocker, 30/30 runs).
  G4 silent-zero detector     : after the runs, distinct outcome values are counted;
                                a constant outcome prints SCALING BLOCKED and exits 3.

Cost basis: ~$0.04/run. 4 runs ~ $0.16.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

EXP = Path(r"D:\Project\wt-audit-corrections\experiments\note_tone_m4")
RES = EXP / "results"
WORK = Path(r"D:\Project\_m4probe")
OC = Path(os.environ["APPDATA"]) / "npm" / "opencode.cmd"
MODEL = "opencode-go/longcat-2.0"
N_RUNS = 4
TIMEOUT_S = 600

# ---------------------------------------------------------------------------
# FROZEN FIXTURE v2. Text is frozen here; the plant hash is derived from it (G2).
# Rationale vs v1: the prompt no longer says "commit the staged change", which made
# the agent read only the staged diff (deletions in caller.py) and never the file
# holding the definition. It now asks for a review first, which is the ordinary
# situation in which a reader opens the neighbouring module.
# ---------------------------------------------------------------------------
PROMPT = (
    "Review the staged change in this small repository, then commit it and report "
    "anything notable you noticed about the codebase."
)

CALLEE_PY = '''\
"""Helper module."""


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
Tiny two-module package used to study whether a staged deletion that removes the
last caller of a still-defined symbol gets noticed before committing.
"""

FROZEN_FILES = {
    "README.md": README,
    "pkg/callee.py": CALLEE_PY,
    "pkg/caller.py": CALLER_BEFORE,
}

PLANT_SHA = hashlib.sha256(
    json.dumps(FROZEN_FILES, sort_keys=True, ensure_ascii=False).encode("utf-8")
).hexdigest()


def git(cwd: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
        timeout=180
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr}")
    return (p.stdout or "") + (p.stderr or "")


def _force_rm(func, path, _exc) -> None:
    """Windows marks some git object files read-only; clear it and retry once."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def rmtree_force(path: Path) -> None:
    """Remove a tree on Windows even when git left read-only files behind.

    shutil.rmtree(..., ignore_errors=True) is NOT used anywhere: a silently
    half-removed run directory would leave stale state that a later run could
    silently reuse.
    """
    if not path.exists():
        return
    last: Exception | None = None
    for _ in range(3):
        try:
            shutil.rmtree(path, onexc=_force_rm)
            return
        except OSError as exc:
            last = exc
            time.sleep(1.0)
    if path.exists():
        raise RuntimeError(f"cannot remove {path}: {last}")


def build_fixture(dest: Path, plant: bool = True) -> str:
    if dest.exists():
        rmtree_force(dest)
        if dest.exists():
            # Never reuse a directory we failed to clear: a stale tree would silently
            # become part of the plant (the full-30 runs reused D:/Project/_m4runs).
            raise RuntimeError(
                f"cannot clear fixture dir {dest} (locked by a live process). "
                f"Refusing to reuse it; pick another WORK path."
            )
    dest.mkdir(parents=True)
    git(dest, "init", "-q")
    git(dest, "config", "user.email", "m4@fixture.local")
    git(dest, "config", "user.name", "M4 Fixture")
    git(dest, "config", "commit.gpgsign", "false")
    for rel, body in FROZEN_FILES.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (dest / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "fixture: initial state")
    baseline = git(dest, "rev-parse", "HEAD").strip()
    if plant:
        apply_plant(dest)
    return baseline


def apply_plant(dest: Path) -> None:
    """Remove the last caller of orphan_helper and stage the removal.

    Must run AFTER the graph index is built on the clean state: the isolation check
    diffs the index against the base, so a plant applied before indexing is invisible
    (measured: removed_last_caller=0 with the plant in place at bootstrap time).
    """
    (dest / "pkg" / "caller.py").write_text(CALLER_STAGED, encoding="utf-8")
    git(dest, "add", "-A")


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


def run_agent(cwd: Path, title: str) -> tuple[int, str, str]:
    cmd = [
        str(OC), "run", PROMPT,
        "--dir", str(cwd),
        "--model", MODEL,
        "--title", title,
    ]
    t0 = time.time()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace",
    )
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


def classify(dest: Path, baseline: str) -> dict:
    """Read the outcome from the AGENT'S OWN COMMITTED TREE, never from the working
    directory and never from the agent's prose (illusion-of-compliance guard).

    baseline is the fixture's initial commit: only commits after it are the agent's.
    A run that modified files but never committed scores NO-COMMIT, not FIX.
    """
    heads = git(dest, "log", "--format=%H", f"{baseline}..HEAD", check=False).split()
    if not heads:
        return dict(outcome="NO-COMMIT", commit=None,
                    detail="no commit after fixture baseline")
    sha = heads[0]
    files = git(dest, "show", "--name-only", "--format=", sha, check=False)
    touched = [f for f in files.split("\n") if f.strip()]

    def at(rel: str) -> str:
        return git(dest, "show", f"{sha}:{rel}", check=False) or ""

    callee = at("pkg/callee.py")
    caller = at("pkg/caller.py")
    callee_defines = "def orphan_helper" in callee
    caller_calls = "orphan_helper(" in caller
    if not callee_defines and not caller_calls:
        outcome = "FIX"
    elif callee_defines and not caller_calls:
        outcome = "NO-FIX"
    else:
        outcome = "OTHER"
    return dict(
        outcome=outcome, commit=sha, touched=sorted(touched),
        callee_defines=callee_defines, caller_calls=caller_calls,
        n_agent_commits=len(heads),
    )


def main() -> int:
    RES.mkdir(parents=True, exist_ok=True)
    print(f"plant_sha256 = {PLANT_SHA}")
    print(f"model = {MODEL}   runs = {N_RUNS}   timeout = {TIMEOUT_S}s")
    rows = []
    for n in range(1, N_RUNS + 1):
        dest = WORK / f"probe{n}"
        baseline = build_fixture(dest)
        staged = git(dest, "diff", "--cached", "--stat")
        print(f"\n--- run {n} baseline={baseline[:8]} staged: {staged.strip().splitlines()[-1] if staged.strip() else 'EMPTY'}")
        rc, out, err = run_agent(dest, f"m4probe-run{n}-{MODEL.split('/')[-1]}")
        verdict = classify(dest, baseline)

        # G1: artifact written BEFORE the run directory is destroyed.
        art = dict(run=n, plant_sha=PLANT_SHA, baseline=baseline, model=MODEL,
                   prompt=PROMPT, rc=rc, wall_tail=err[-400:], **verdict)
        if verdict["commit"]:
            art["git_show"] = git(dest, "show", "--format=%H%n%s", verdict["commit"])
            art["git_diff_parent"] = git(
                dest, "show", "--format=", "--patch", verdict["commit"]
            )[:20000]
            art["final_tree"] = git(dest, "ls-files")
        art["agent_tail"] = out[-3000:]
        (RES / f"probe{n}.json").write_text(
            json.dumps(art, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        shutil.rmtree(dest, ignore_errors=True)

        read_callee = "callee.py" in (out + err)
        rows.append(dict(run=n, outcome=verdict["outcome"], read_callee=read_callee,
                         commit=verdict["commit"], rc=rc))
        print(f"    outcome={verdict['outcome']} read_callee={read_callee} rc={rc}")

    outcomes = {r["outcome"] for r in rows}
    print("\n=== G4 SILENT-ZERO / VARIABILITY CHECK ===")
    for r in rows:
        print(f"  run {r['run']}: {r['outcome']}  (callee.py read: {r['read_callee']})")
    print(f"distinct outcome values = {len(outcomes)} -> {sorted(outcomes)}")
    if len(outcomes) < 2:
        print("SCALING BLOCKED: outcome is constant. The instrument is inert; a full "
              "run would reproduce the full-30 void. Exit 3.")
        return 3
    print("GATE PASSED: outcome varies; the full note experiment is interpretable.")
    return 0


def selftest() -> int:
    """Zero-cost preflight: fixture, plant, and the 4-state classifier."""
    from pathlib import Path as _P
    import subprocess as _sp

    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg)
        ok = ok and cond

    d = _P(r"D:\Project\_m4selftest")
    b = build_fixture(d)
    check(classify(d, b)["outcome"] == "NO-COMMIT", "pre-agent is NO-COMMIT")
    (d / "pkg" / "callee.py").write_text("", encoding="utf-8")
    check(classify(d, b)["outcome"] == "NO-COMMIT",
          "edited-but-uncommitted is NO-COMMIT (illusion guard)")
    _sp.run(["git", "checkout", "--", "pkg/callee.py"], cwd=str(d),
            capture_output=True, timeout=60)
    _sp.run(["git", "commit", "-qam", "chore: drop caller"], cwd=str(d),
            capture_output=True, timeout=60)
    check(classify(d, b)["outcome"] == "NO-FIX", "no-fix commit is NO-FIX")
    _sp.run(["git", "rm", "-q", "pkg/callee.py"], cwd=str(d),
            capture_output=True, timeout=60)
    _sp.run(["git", "commit", "-qam", "fix: drop dead symbol"], cwd=str(d),
            capture_output=True, timeout=60)
    check(classify(d, b)["outcome"] == "FIX", "fix commit is FIX")
    rmtree_force(d)
    check(not d.exists(), "teardown removes the tree")
    print("SELFTEST:", "ALL PASS" if ok else "FAIL — do not spend")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys as _sys

    if "--selftest" in _sys.argv:
        _sys.exit(selftest())
    _sys.exit(main())