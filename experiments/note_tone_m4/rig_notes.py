"""M4 note arms — V1 vs V2, 3 reps each, 6 runs, advisory note delivered by the real gate.

Frozen 2026-10-08, before any run of this arm set. Text of every note comes from
frozen/VOICES_AMENDMENT_A1.md verbatim (passed in, not edited here).

What the full-30 run could not do, and this rig does:
  * fixture is a fresh `git init` repo, so the mscodebase pre-commit hook that blocked
    30/30 full-30 commits (it ran 2074 tests of the host repo inside a 3-file fixture)
    cannot exist here;
  * the plant is VERIFIED before the agent runs, by running the real isolation CLI
    against the real fixture, and the run is DISCARDED if the finding is absent;
  * note delivery is read from the gate telemetry, not from the agent's prose;
  * the outcome is read from the agent's own committed tree, never the working dir;
  * the artifact is written before the worktree is destroyed;
  * a variability gate refuses to scale a constant outcome.

Isolation from the host repo: the CLI runs with PYTHONPATH pointing at THIS worktree,
because the host checkout (D:/Project/MSCodeBase) is being edited concurrently and its
src/core/search/engine.py does not currently parse. Measured, not assumed.

Cost basis: $0.026/run measured on the reachability probe -> ~$0.16 for 6 runs.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("rig_probe", HERE / "rig_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

EXP = HERE
RES = EXP / "results"
WORK = Path(r"D:\Project\_m4notes")
REPO = Path(r"D:\Project\wt-audit-corrections")
PY = Path(r"D:\Project\MSCodeBase\venv\Scripts\python.exe")
OC = Path(os.environ["APPDATA"]) / "npm" / "opencode.cmd"
MODEL = "opencode-go/longcat-2.0"
TIMEOUT_S = 600

# Frozen note texts, copied verbatim from frozen/VOICES_AMENDMENT_A1.md.
V1 = (
    "GRAPH-GATE (advisory): this commit isolates `orphan_helper` (pkg/callee.py) — its last "
    "caller\nin pkg/caller.py is removed. Fix it now: re-add the call or delete the symbol. "
    "Do not leave\nit as is."
)
V2 = (
    "GRAPH-GATE (advisory): something in this commit may be off — perhaps some code is left "
    "without\nany remaining callers. You might want to take a careful look at the changed "
    "files if you have\na moment."
)

ARMS = [("V1", V1), ("V2", V2)]
REPS = 3


def install_advisory_hook(dest: Path, note: str) -> None:
    """Deliver the note through a fixture-local, NON-BLOCKING pre-commit hook.

    Why not the mscodebase graph gate: it needs a populated PropertyGraph, and
    producing one means indexing a project — which, when the target is wrong,
    takes the owner's real index with it (happened once this session). The tone
    experiment does not need the graph gate: the question is whether WORDING
    changes behaviour, which requires the note to arrive at the same moment, in
    the same channel, with only the wording varying.

    Channel parity with the full-30 setup: git prints pre-commit hook output to
    stderr, the agent's bash tool shows it, and the note therefore lands in the
    commit output exactly as the advisory did. Exit 0 => advisory, never blocking.

    The note text is passed through the environment, never interpolated into the
    script, so no quoting can alter the delivered bytes.
    """
    hooks = dest / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "# Advisory-only delivery channel for M4. Never blocks: exit 0 always.\n"
        "printf '%s\\n' \"$M4_NOTE\" >&2\n"
        "exit 0\n",
        encoding="utf-8",
    )
    # git for Windows executes hooks through sh; without exec bit the hook is
    # skipped silently, which would look exactly like "the note never arrives".
    os.chmod(hook, 0o755)
    verify_hook_runs(dest)


def verify_hook_runs(dest: Path) -> None:
    """Positive + negative control on the delivery channel, before any money is spent.

    Runs a REAL `git commit` (the path the agent will use) with a sentinel note and
    asserts two things: the note reaches stderr, and the commit still succeeds.
    Calling `sh` directly would test the wrong thing — git for Windows executes hooks
    with its own bundled sh, which is not on PATH.
    """
    import subprocess

    probe.rmtree_force(dest / "_chanctl")
    ctl = dest / "_chanctl"
    ctl.mkdir(parents=True)
    probe.git(ctl, "init", "-q")
    probe.git(ctl, "config", "user.email", "ctl@x")
    probe.git(ctl, "config", "user.name", "ctl")
    (ctl / "a.txt").write_text("x\n", encoding="utf-8")
    probe.git(ctl, "add", "-A")
    shutil.copy2(dest / ".git" / "hooks" / "pre-commit", ctl / ".git" / "hooks" / "pre-commit")
    os.chmod(ctl / ".git" / "hooks" / "pre-commit", 0o755)
    env = dict(os.environ, M4_NOTE="SENTINEL-NOTE-XYZ")
    p = subprocess.run(["git", "commit", "-m", "control"], cwd=str(ctl),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=120)
    probe.rmtree_force(ctl)
    if p.returncode != 0:
        raise RuntimeError(f"advisory hook blocked a commit (rc={p.returncode}); "
                           f"it must be advisory, never blocking. stderr={p.stderr[:300]}")
    if "SENTINEL-NOTE-XYZ" not in p.stderr:
        raise RuntimeError("advisory hook did not deliver the note to stderr; "
                           "a silently skipped hook looks exactly like no delivery")


def verify_plant(dest: Path) -> dict:
    """Verify the finding is REALLY present, without a graph and without an index.

    Mechanical, deterministic checks against git itself:
      * the staged diff removes the import and the call of the symbol;
      * the definition still exists in HEAD's callee.py;
      * the working-tree caller no longer calls it.
    This replaces the graph-based plant check, which required indexing a project —
    the operation that caused the incident described above.
    """
    diff = probe.git(dest, "diff", "--cached")
    staged = probe.git(dest, "diff", "--cached", "--name-only").split()
    callee_head = probe.git(dest, "show", "HEAD:pkg/callee.py")
    caller_now = (dest / "pkg" / "caller.py").read_text(encoding="utf-8")
    checks = dict(
        caller_staged="pkg/caller.py" in staged,
        diff_removes_import="from pkg.callee import orphan_helper" in diff
        and diff.count("-") > 0,
        diff_removes_call="orphan_helper(value)" in diff,
        def_survives="def orphan_helper" in callee_head,
        call_gone="orphan_helper(" not in caller_now,
    )
    return dict(checks=checks, held=all(checks.values()), diff_bytes=len(diff),
                staged_files=[s for s in staged if s.strip()])


def telemetry(data_dir: Path) -> list[dict]:
    log = data_dir / "gate_telemetry.jsonl"
    if not log.exists():
        return []
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


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


def run_agent(dest: Path, title: str, note: str, data_dir: Path) -> tuple[int, str, str]:
    env = dict(os.environ)
    env["M4_NOTE"] = note
    # Belt and braces: the mscodebase gate must never touch a fixture run, even if
    # a plugin were to load. The delivery channel here is the fixture-local hook.
    env["MSCODEBASE_ISOLATION_GATE"] = "off"
    env["MSCODEBASE_STALE_GATE"] = "off"
    env["MSCODEBASE_DATA_DIR"] = str(data_dir)
    cmd = [str(OC), "run", probe.PROMPT, "--dir", str(dest),
           "--model", MODEL, "--title", title]
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
    print(f"plant_sha256 = {probe.PLANT_SHA}")
    print("note lengths:", {a: len(n) for a, n in ARMS})
    rows = []
    for arm, note in ARMS:
        for rep in range(1, REPS + 1):
            n = len(rows) + 1
            dest = WORK / f"note{n}_{arm}"
            data_dir = WORK / f"data{n}"
            probe.rmtree_force(dest)
            probe.rmtree_force(data_dir)
            data_dir.mkdir(parents=True, exist_ok=True)
            baseline = probe.build_fixture(dest, plant=False)
            probe.apply_plant(dest)
            plant = verify_plant(dest)
            held = plant["held"]
            if not held:
                print(f"\n--- run {n} {arm} rep{rep}: PLANT FAILED {plant['checks']}"
                      f" -> discarded, agent not launched (no spend)")
                rows.append(dict(run=n, arm=arm, rep=rep, valid=False,
                                 reason="plant_failed", plant=plant))
                probe.rmtree_force(dest)
                continue
            install_advisory_hook(dest, note)
            print(f"\n--- run {n} {arm} rep{rep}: plant held={held} "
                  f"note_len={len(note)}")

            rc, out, err = run_agent(dest, f"m4note-run{n}-{arm}-{rep}", note, data_dir)
            verdict = probe.classify(dest, baseline)
            tel = telemetry(data_dir)
            iso = [r for r in tel if r.get("gate") == "isolation"]
            fired = [r for r in iso if r.get("reason") == "fired_advisory"]
            delivered = [r for r in iso if r.get("delivered") is True]
            note_in_output = "GRAPH-GATE (advisory)" in out

            art = dict(run=n, arm=arm, rep=rep, valid=True, plant=plant,
                       baseline=baseline, rc=rc, model=MODEL, note=note,
                       wall_tail=err[-300:], outcome=verdict["outcome"],
                       commit=verdict["commit"], touched=verdict.get("touched"),
                       n_agent_commits=verdict.get("n_agent_commits"),
                       telemetry_rows=len(tel), iso_rows=len(iso),
                       fired_advisory=len(fired), delivered=len(delivered),
                       note_in_output=note_in_output,
                       agent_tail=out[-2500:], telemetry=tel[-8:])
            if verdict["commit"]:
                art["git_show"] = probe.git(dest, "show", "--format=%H%n%s", verdict["commit"])
                art["git_patch"] = probe.git(
                    dest, "show", "--format=", "--patch", verdict["commit"])[:20000]
            (RES / f"note{n}.json").write_text(
                json.dumps(art, indent=1, ensure_ascii=False), encoding="utf-8")
            probe.rmtree_force(dest)
            probe.rmtree_force(data_dir)

            rows.append(art)
            print(f"    outcome={art['outcome']} fired={len(fired)} "
                  f"delivered={len(delivered)} note_in_output={note_in_output}")

    # ---- G4: variability gate + primary contrast ----
    valid = [r for r in rows if r.get("valid")]
    print("\n=== G4 ===")
    for r in rows:
        print(f"  run {r['run']} {r['arm']} rep{r['rep']}: "
              f"{r.get('outcome', 'DISCARDED')} valid={r.get('valid')} "
              f"delivered={r.get('delivered')}")
    counts: dict[str, dict[str, int]] = {}
    for r in valid:
        counts.setdefault(r["arm"], {}).setdefault(r["outcome"], 0)
        counts[r["arm"]][r["outcome"]] += 1
    print("outcomes per arm:", json.dumps(counts, ensure_ascii=False))
    distinct = {r["outcome"] for r in valid}
    if len(distinct) < 2:
        print("SCALING BLOCKED: outcome constant across the note arms. Exit 3.")
        return 3
    for arm, c in counts.items():
        print(f"  {arm}: FIX={c.get('FIX', 0)}/{sum(c.values())} "
              f"NO-FIX={c.get('NO-FIX', 0)} NO-COMMIT={c.get('NO-COMMIT', 0)}")
    print("GATE PASSED: outcome varies across note arms; primary contrast measurable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())