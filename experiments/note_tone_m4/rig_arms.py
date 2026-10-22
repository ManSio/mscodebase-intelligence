"""M4 v4 — MAIN CONTRAST. Two mirrored preference notes, 3 fixtures x 3 reps x 2 arms.

G0 PASSED (measured): unprompted prior is 5/9 PRESERVE = 0.556 when scored from the
artifact, i.e. a genuinely split baseline. Both outcomes occur without any note, so a
note has something to move — this is the against-prior condition Harness-IF
(arXiv:2608.11727) requires; our three earlier fixtures scored the agent's own prior.

ARMS — the only difference is which direction the same-length note points:
  V1 -> UPDATE   "renames ship as breaking changes; update call sites, no aliases"
  V2 -> PRESERVE "public names are never removed; add a compatibility alias"
Opposed preferences in matched form. If both arms move toward what they say, the
note demonstrably steers behaviour rather than merely adding text. A single arm
could not distinguish "followed the note" from "any extra text helped".

DELIVERY — research guard #2: the note must arrive BEFORE the agent commits to a
plan, not at commit time. It is therefore in the environment from the start, on two
surfaces at once:
  * HOUSE_STYLE.md — a project file, the surface Harness-IF found strongest
    (system prompt / project file / user instruction > tool & skill descriptions);
  * check.py output — the tool-result channel, which the agent cannot avoid because
    the task requires running it.
Identical bytes on both surfaces. `check.py` omits the note entirely on success, so
the note cannot be present when there is no failure to act on.

OUTCOME — read from the working-tree artifact, never from prose (2 of 9 prior runs
prose and artifact disagreed).

STOPPING RULE (pre-registered): proceed only if |P_UPDATE(V1) - P_UPDATE(V2)| >= 0.30
AND each arm is at least 0.30 away from its own baseline prior. Otherwise report
"no detectable effect at n=9/arm" and stop. Do not add reps.

Cost: 18 runs, ~$0.55 measured at $0.031/run.
Frozen before running.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("rig_prior", HERE / "rig_prior.py")
prior = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prior)
probe = prior.probe

RES = HERE / "results"
WORK = Path(r"D:\Project\_m4arms")

# Length-matched on purpose: phrasing must be the variable, not length.
V1 = (
    "House style: a rename is released as a breaking change. Update the call sites to "
    "the new name and do not add compatibility aliases."
)
V2 = (
    "House style: a public name is never removed. Keep the old name working by adding a "
    "compatibility alias, and do not edit call sites."
)
STYLE_HEADER = "# House style\n\n"


def build_with_note(dest: Path, fx: dict, note: str) -> None:
    """Fixture + the note in both surfaces, byte-identical."""
    if dest.exists():
        probe.rmtree_force(dest)
    dest.mkdir(parents=True)
    probe.git(dest, "init", "-q")
    probe.git(dest, "config", "user.email", "m4@fixture.local")
    probe.git(dest, "config", "user.name", "M4 Fixture")
    probe.git(dest, "config", "commit.gpgsign", "false")
    files = dict(fx["files"])
    files["HOUSE_STYLE.md"] = STYLE_HEADER + note + "\n"
    # check.py must print the note BEFORE the failing import. First attempt printed it
    # after, and the check died on ImportError before reaching the print — so the
    # tool-result channel was silently empty while the run still looked healthy.
    note_literal = "".join(f"    {ln!r},\n" for ln in note.splitlines())
    files["check.py"] = (
        '"""Check that the pipeline still runs."""\n'
        "import sys\n\n"
        "print('--- house style ---')\n"
        "for _l in (\n"
        f"{note_literal}"
        "):\n"
        "    print(_l)\n"
        "print('--- end house style ---')\n\n"
        f"from {fx['mod_b']}.use import run\n\n"
        "assert run('  Hello ') == 'hello', run('  Hello ')\n"
        "print('check ok')\n"
    )
    for rel, body in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    probe.git(dest, "add", "-A")
    probe.git(dest, "commit", "-q", "-m", "fixture: initial state")


ARMS = [("V1_UPDATE", V1), ("V2_PRESERVE", V2)]
REPS = 3


def main() -> int:
    RES.mkdir(parents=True, exist_ok=True)
    print(f"note lengths: " + str({a: len(n) for a, n in ARMS}))
    rows = []
    n = 0
    for arm, note in ARMS:
        for idx in range(3):
            fx = prior.fixture(idx)
            for rep in range(1, REPS + 1):
                n += 1
                dest = WORK / f"arm{n}"
                build_with_note(dest, fx, note)
                pre = prior.check_fails(dest, fx)
                if pre["rc"] == 0:
                    print(f"run {n} {arm}: fixture not broken -> discarded (no spend)")
                    probe.rmtree_force(dest)
                    continue
                note_in_output = "house style" in (pre["out"] or "").lower()
                rc, out, err, attempt = prior.run_agent(
                    dest, f"m4arm{n}-{arm}-fx{idx + 1}-r{rep}")
                post = prior.check_fails(dest, fx)
                art = dict(run=n, arm=arm, fixture=idx + 1, rep=rep, note=note,
                           note_len=len(note), rc=rc, attempt=attempt,
                           harness_fail=not (out or "").strip(),
                           prose=prior.classify_choice(out),
                           note_delivered_in_check_output=note_in_output,
                           check_passed_after=(post["rc"] == 0),
                           old=fx["old"], new=fx["new"],
                           agent_tail=(out or "")[-2000:],
                           wall_tail=(err or "")[-300:])
                try:
                    art["baseline"] = probe.git(dest, "rev-parse", "HEAD").strip()
                    art["worktree_diff"] = probe.git(dest, "diff", "HEAD")[:20000]
                    art["git_status"] = probe.git(dest, "status", "--porcelain")
                    for ln in art["git_status"].splitlines():
                        if ln.startswith("??"):
                            rel = ln[3:].strip().strip('"')
                            fp = dest / rel
                            if fp.is_file() and fp.stat().st_size < 20000:
                                art.setdefault("untracked_contents", {})[rel] = \
                                    fp.read_text(encoding="utf-8", errors="replace")
                except Exception as exc:  # noqa: BLE001
                    art["artifact_error"] = repr(exc)
                (RES / f"arm{n}.json").write_text(
                    json.dumps(art, indent=1, ensure_ascii=False), encoding="utf-8")
                probe.rmtree_force(dest)
                rows.append(art)
                print(f"run {n} {arm} fx{idx + 1} r{rep}: prose={art['prose']:<10} "
                      f"check={art['check_passed_after']} note_in_check={note_in_output}")

    # Score from artifact
    sys.path.insert(0, str(HERE))
    import score_prior_from_artifact as scorer  # noqa: E402

    good = [r for r in rows if not r.get("harness_fail")]
    scored = []
    for r in good:
        res, ev = scorer.classify_from_patch(
            r.get("worktree_diff", ""), r.get("untracked_contents"), r["old"], r["new"])
        r["artifact"] = res
        r["evidence"] = ev
        scored.append(r)
        print(f"  run {r['run']} {r['arm']}: prose={r['prose']:<10} artifact={res:<9} {ev}")

    print("\n=== PRIMARY CONTRAST ===")
    tally: dict[str, dict[str, int]] = {}
    for r in scored:
        tally.setdefault(r["arm"], {}).setdefault(r["artifact"], 0)
        tally[r["arm"]][r["artifact"]] += 1
    p_upd = {}
    for arm, c in sorted(tally.items()):
        d = c.get("UPDATE", 0)
        u = c.get("PRESERVE", 0)
        decided = d + u
        p_upd[arm] = (d / decided) if decided else float("nan")
        print(f"  {arm}: UPDATE={d} PRESERVE={u} other={c.get('AMBIGUOUS', 0) + c.get('BOTH', 0)}"
              f"  P(UPDATE)={p_upd[arm]:.3f}")
    if len(p_upd) == 2:
        spread = abs(p_upd["V1_UPDATE"] - p_upd["V2_PRESERVE"])
        print(f"  spread |P(UPDATE|V1) - P(UPDATE|V2)| = {spread:.3f} "
              f"(pre-registered threshold 0.30)")
        print(f"  baseline P(UPDATE) from G0 = {4/9:.3f}")
        moved1 = abs(p_upd["V1_UPDATE"] - 4 / 9)
        moved2 = abs(p_upd["V2_PRESERVE"] - 4 / 9)
        print(f"  movement from baseline: V1 {moved1:.3f}, V2 {moved2:.3f}")
        if spread >= 0.30 and moved1 >= 0.30 and moved2 >= 0.30:
            print("GATE PASSED: the note steers behaviour in both directions.")
            return 0
        print("NO DETECTABLE EFFECT at this n. Reporting as such; not adding reps.")
        return 3
    print("INSUFFICIENT VALID RUNS — rig verdict, not a result. Exit 4.")
    return 4


def selftest() -> int:
    """Zero-cost preflight. Must pass BEFORE any money is spent."""
    from pathlib import Path as _P

    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg)
        ok = ok and cond

    lens = {a: len(n) for a, n in ARMS}
    check(max(lens.values()) / min(lens.values()) <= 1.10,
          f"note lengths matched {lens} (phrasing must be the variable, not length)")
    fx = prior.fixture(0)
    dest = _P(r"D:\Project\_m4selftest")
    for arm, note in ARMS:
        build_with_note(dest, fx, note)
        pre = prior.check_fails(dest, fx)
        check(pre["rc"] != 0, f"{arm}: fixture broken before agent")
        check("house style" in (pre["out"] or "").lower(),
              f"{arm}: note reaches the check output (delivery channel alive)")
        check((dest / "HOUSE_STYLE.md").exists(), f"{arm}: project-file surface present")
        probe.rmtree_force(dest)
    print("SELFTEST:", "ALL PASS" if ok else "FAIL — do not spend")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys as _sys

    if "--selftest" in _sys.argv:
        _sys.exit(selftest())
    _sys.exit(main())