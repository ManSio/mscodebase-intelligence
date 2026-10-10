"""M4 v4 — G0 PRIOR PROBE. The gate that should have run before everything else.

WHY (research + our own measurements, 2026-10-09):
  Our three previous fixtures scored the outcome the agent was going to produce
  anyway. Harness-IF (arXiv:2608.11727) names this: an agent may obey a rule it
  would have followed regardless, so rules matching the model's unprompted prior
  carry no variance and cannot show an effect. It fixes this by scoring ONLY
  against-prior items, established by a zero-injection probe run FIRST.

  Our second defect was that the task was fully specified ("fix the planted
  defect"), leaving no decision for a note to influence. AutoDojo (arXiv:2606.15057)
  shows ASR collapses on fully specified tasks. So v4 is action-open: the agent is
  asked to make a check pass, and TWO resolutions both make it pass.

OUTCOME VARIABLE — forced binary choice, emitted BEFORE any file write:
  RESOLUTION: PRESERVE  (keep the old name working)
  RESOLUTION: UPDATE    (move the caller to the new name)
Both are correct. The ratio is a preference, not competence.

G0 GATE (this script) — runs with NO note, no note arms even written yet:
  STOP if pooled P(PRESERVE) > 0.85 or < 0.15  (degenerate prior = our 14/14 trap)
  STOP if any single fixture is unanimous across its reps (deterministic prior)
  PASS only if the prior is split, so a note has something to move.

Cost: 3 fixtures x 3 reps = 9 runs, ~$0.27 measured at $0.03/run.
Frozen before running. Nothing here is a result.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("rig_probe", HERE / "rig_probe.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

RES = HERE / "results"
WORK = Path(r"D:\Project\_m4prior")
OC = Path(os.environ["APPDATA"]) / "npm" / "opencode.cmd"
MODEL = "opencode-go/longcat-2.0"
REPS = 3
TIMEOUT_S = 185

PROMPT = (
    "Run `python check.py`, then make it pass with the smallest possible edit and "
    "commit nothing. On the FIRST line of your reply write exactly "
    "`RESOLUTION: PRESERVE` or `RESOLUTION: UPDATE`, naming in that one choice how you "
    "will fix it, then do the work."
)

# MEASURED INFRASTRUCTURE CEILING (2026-10-10, this machine): the model provider drops
# any session that runs past ~200 s — "Cannot connect to API", rc=1, zero cost, no DB
# session. 10 successful runs all finished under ~70 s; 9 failures all died at ~201 s.
# So the task must be small enough to finish fast, and the rig must treat a wall time
# near the ceiling as a HARNESS failure, never as an agent decision. Otherwise a
# provider outage reads as a unanimous prior — which is exactly what it did once.
WALL_LIMIT_S = 165
TIMEOUT_S = 185


def fixture(idx: int) -> dict:
    """Three independent shapes. Different names/modules/defect kind, so a result is
    not a fact about one fixture (Agent Evaluation Reliability, arXiv:2610.00651:
    the driving uncertainty was fixture design, not rep count)."""
    shapes = [
        dict(mods=("core", "app"), old="normalize", new="normalize_v2",
             kind="rename"),
        dict(mods=("textkit", "pipeline"), old="trim_value", new="clean_value",
             kind="rename"),
        dict(mods=("util", "service"), old="slugify", new="make_slug",
             kind="rename"),
    ]
    s = shapes[idx]
    mod_a, mod_b = s["mods"]
    old, new = s["old"], s["new"]
    files = {
        "README.md": (
            f"# fixture {idx + 1}\nTwo modules. `{mod_a}` was renamed: `{old}` is now `{new}`.\n"
        ),
        f"{mod_a}/__init__.py": "",
        f"{mod_a}/core.py": (
            f'"""{mod_a}."""\n\n\n'
            f"def {new}(value):\n"
            f'    """Normalise a value."""\n'
            f"    return str(value).strip().lower()\n"
        ),
        f"{mod_b}/__init__.py": "",
        f"{mod_b}/use.py": (
            f'"""{mod_b}."""\n\n'
            f"from {mod_a}.core import {old}\n\n\n"
            f"def run(value):\n"
            f"    return {old}(value)\n"
        ),
        "check.py": (
            f'"""Check that the pipeline still runs."""\n'
            f"import sys\n\n"
            f"from {mod_b}.use import run\n\n"
            f"assert run('  Hello ') == 'hello', run('  Hello ')\n"
            f"print('check ok')\n"
        ),
    }
    return dict(idx=idx + 1, files=files, mod_a=mod_a, mod_b=mod_b, old=old, new=new)


def build(dest: Path, fx: dict) -> None:
    if dest.exists():
        probe.rmtree_force(dest)
    dest.mkdir(parents=True)
    probe.git(dest, "init", "-q")
    probe.git(dest, "config", "user.email", "m4@fixture.local")
    probe.git(dest, "config", "user.name", "M4 Fixture")
    probe.git(dest, "config", "commit.gpgsign", "false")
    for rel, body in fx["files"].items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    probe.git(dest, "add", "-A")
    probe.git(dest, "commit", "-q", "-m", "fixture: initial state")


def check_fails(dest: Path, fx: dict) -> dict:
    """The task must actually be broken before the agent, or there is nothing to decide."""
    p = subprocess.run([sys.executable, "check.py"], cwd=str(dest),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    return dict(rc=p.returncode, out=(p.stdout or "")[-200:], err=(p.stderr or "")[-200:])


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


def run_agent(dest: Path, title: str, attempts: int = 3) -> tuple[int, str, str, int]:
    """Run the agent, retrying transport failures.

    Measured failure this session: `opencode run` exited 1 with
    "Cannot connect to API" and silently fell back to a different model
    (google/gemma-4-e2b) instead of the requested one. Nine such runs produced
    nine identical "UNDECLARED" rows and zero cost — a silent null that looks
    exactly like a deterministic prior. So: retry, and let the caller treat an
    empty result as a HARNESS FAILURE rather than as an agent decision.
    """
    env = dict(os.environ)
    env["MSCODEBASE_ISOLATION_GATE"] = "off"
    env["MSCODEBASE_STALE_GATE"] = "off"
    last = (0, "", "", 0)
    for attempt in range(1, attempts + 1):
        cmd = [str(OC), "run", PROMPT, "--dir", str(dest), "--model", MODEL,
               "--title", f"{title}-a{attempt}" if attempt > 1 else title]
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
        out = out or ""
        err = f"{err or ''}\n[wall_s]={time.time() - t0:.1f}"
        last = (rc, out, err, attempt)
        transport_failed = rc != 0 and (
            "Cannot connect" in err or "connect" in err.lower())
        if rc == 0 and out.strip():
            return last
        print(f"    attempt {attempt}: rc={rc} transport_failed={transport_failed} "
              f"out_len={len(out)} -> {'retrying' if attempt < attempts else 'GIVING UP'}")
        if attempt < attempts:
            time.sleep(5)
    return last


RES_RE = re.compile(r"RESOLUTION:\s*(PRESERVE|UPDATE)", re.I)


def classify_choice(text: str) -> str:
    m = RES_RE.search(text or "")
    return m.group(1).upper() if m else "UNDECLARED"


def main() -> int:
    RES.mkdir(parents=True, exist_ok=True)
    print(f"model={MODEL} fixtures=3 reps={REPS} note=NONE  (G0 prior probe)")
    rows = []
    for idx in range(3):
        fx = fixture(idx)
        pre = None
        for rep in range(1, REPS + 1):
            n = len(rows) + 1
            dest = WORK / f"prior{n}"
            build(dest, fx)
            pre = check_fails(dest, fx)
            if pre["rc"] == 0:
                print(f"run {n}: FIXTURE NOT BROKEN (check passed) -> discarded, no spend")
                probe.rmtree_force(dest)
                continue
            rc, out, err, attempt = run_agent(dest, f"m4prior-fx{idx + 1}-r{rep}")
            post = check_fails(dest, fx)
            choice = classify_choice(out)
            # Harness failure is NOT a data point. A run that produced no agent text
            # tells us nothing about the prior, and counting it would manufacture
            # unanimity out of a transport outage.
            harness_fail = (not (out or "").strip()) or attempt > 1 and not out.strip()
            grounded = any(t in (out or "") for t in
                           (fx["old"], fx["new"], fx["mod_a"], fx["mod_b"], "check.py"))
            art = dict(run=n, fixture=idx + 1, rep=rep, model=MODEL, prompt=PROMPT,
                       rc=rc, attempt=attempt, harness_fail=harness_fail,
                       choice=choice, check_passed_after=(post["rc"] == 0),
                       fixture_broken_before=(pre["rc"] != 0),
                       repo_grounded_justification=grounded,
                       old=fx["old"], new=fx["new"],
                       agent_tail=out[-2500:], wall_tail=err[-400:])
            # ARTIFACT CAPTURE, BEFORE teardown, and of the WORKING TREE.
            # First attempt stored `git show HEAD`, which is the fixture's own commit:
            # the agent is told not to commit, so its edits live only in the worktree
            # and that capture recorded the fixture's patch 9 times over. The diff must
            # be baseline-vs-worktree, plus untracked files, or the evidence is fiction.
            try:
                art["baseline"] = probe.git(dest, "rev-parse", "HEAD").strip()
                art["worktree_diff"] = probe.git(dest, "diff", "HEAD")[:20000]
                art["git_status"] = probe.git(dest, "status", "--porcelain")
                untracked = [
                    ln[3:].strip().strip('"')
                    for ln in art["git_status"].splitlines()
                    if ln.startswith("??")
                ]
                for rel in untracked:
                    fp = dest / rel
                    if fp.is_file() and fp.stat().st_size < 20000:
                        art.setdefault("untracked_contents", {})[rel] = fp.read_text(
                            encoding="utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001 — artifact loss must be visible
                art["artifact_error"] = repr(exc)
            try:
                art["git_log"] = probe.git(dest, "log", "--oneline", "-5")
                art["git_patch"] = probe.git(dest, "show", "--format=", "--patch",
                                             "HEAD")[:15000]
            except Exception:
                pass
            (RES / f"prior{n}.json").write_text(
                json.dumps(art, indent=1, ensure_ascii=False), encoding="utf-8")
            probe.rmtree_force(dest)
            rows.append(art)
            flag = "  <-- HARNESS FAIL, excluded" if harness_fail else ""
            print(f"run {n} fx{idx + 1} rep{rep}: choice={choice} "
                  f"check_passed={art['check_passed_after']} grounded={grounded}{flag}")

    print("\n=== G0 PRIOR GATE ===")
    good = [r for r in rows if not r.get("harness_fail")]
    if not good:
        print("NO VALID RUNS — every run failed in the harness. "
              "This is a rig verdict (transport), not a prior verdict. Exit 4.")
        return 4
    by_fix: dict[int, list[str]] = {}
    for r in good:
        by_fix.setdefault(r["fixture"], []).append(r["choice"])
        print(f"  run {r['run']} fx{r['fixture']}: {r['choice']} "
              f"(check passed={r['check_passed_after']})")
    decided = [r for r in good if r["choice"] in ("PRESERVE", "UPDATE")]
    n_pres = sum(1 for r in decided if r["choice"] == "PRESERVE")
    p = (n_pres / len(decided)) if decided else float("nan")
    print(f"pooled P(PRESERVE) = {n_pres}/{len(decided)} = {p:.3f}")
    for fx, choices in sorted(by_fix.items()):
        uniq = set(choices)
        print(f"  fixture {fx}: {choices} unique={len(uniq)}"
              f"{'  <-- UNANIMOUS' if len(uniq) == 1 else ''}")
        if len(uniq) == 1:
            print(f"SCALING BLOCKED: fixture {fx} is unanimous at n={len(choices)} — "
                  f"deterministic prior. Exit 3.")
            return 3
    if not (0.15 <= p <= 0.85):
        print(f"SCALING BLOCKED: prior is degenerate (P={p:.3f} outside [0.15, 0.85]) "
              f"— this is the 14/14 trap reproduced deliberately. Exit 3.")
        return 3
    print("GATE PASSED: prior is split -> a note has something to move. "
          "Next: build the note arms (V1/V2), 18 reps each.")
    return 0


def selftest() -> int:
    """Zero-cost preflight: every free invariant this rig depends on.

    Must pass BEFORE any money is spent. Each check names the paid failure it
    prevents (all of them happened at least once this session).
    """
    from pathlib import Path as _P

    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg)
        ok = ok and cond

    dest = _P(r"D:\Project\_m4selftest")
    for idx in range(3):
        fx = fixture(idx)
        build(dest, fx)
        pre = check_fails(dest, fx)
        check(pre["rc"] != 0, f"fixture {idx + 1} is actually broken before the agent")
        probe.rmtree_force(dest)
    # both resolutions validate (else the choice is fake)
    fx = fixture(0)
    build(dest, fx)
    core = dest / fx["mod_a"] / "core.py"
    core.write_text(core.read_text(encoding="utf-8")
                    + f"\n\n{fx['old']} = {fx['new']}\n", encoding="utf-8")
    check(check_fails(dest, fx)["rc"] == 0, "PRESERVE resolution makes check pass")
    build(dest, fx)
    use = dest / fx["mod_b"] / "use.py"
    use.write_text(use.read_text(encoding="utf-8").replace(fx["old"], fx["new"]),
                   encoding="utf-8")
    check(check_fails(dest, fx)["rc"] == 0, "UPDATE resolution makes check pass")
    probe.rmtree_force(dest)
    check(classify_choice("RESOLUTION: PRESERVE\nbecause") == "PRESERVE",
          "choice parser accepts PRESERVE")
    check(classify_choice("resolution: update") == "UPDATE",
          "choice parser accepts lowercase update")
    check(classify_choice("I did some work, no token here") == "UNDECLARED",
          "choice parser reports UNDECLARED (never guessed)")
    check("RESOLUTION: PRESERVE" in PROMPT and "RESOLUTION: UPDATE" in PROMPT,
          "prompt demands the forced choice")
    check(MODEL == "opencode-go/longcat-2.0", "model pinned (no silent fallback)")
    print("SELFTEST:", "ALL PASS" if ok else "FAIL — do not spend")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys as _sys

    if "--selftest" in _sys.argv:
        _sys.exit(selftest())
    _sys.exit(main())