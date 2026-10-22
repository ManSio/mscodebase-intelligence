"""M4 v5 — PHRASING CONTRAST at controlled direction. 2 arms x 3 fixtures x 3 reps = 18 runs.

PREREGISTERED (frozen before running, 2026-10-10):

  H1  imperative+muted   -> UPDATE   "House style: a rename is a breaking change.
      Update the call sites to the new name. Do not keep the old name working with an alias."
  H2  hedged+expanded    -> UPDATE   same direction, hedged mood, noisy, length-matched

  Both arms point the SAME way (UPDATE). This is what makes the phrasing separable from
  direction, which v4 could not do: there the two notes were mirrored in meaning, so the
  measurement was steering, not wording.

  Controls borrowed from the literature and from our own runs:
    * benign twin / length control = the G0 no-note baseline (9 runs, already measured,
      P(UPDATE)=4/9=0.444). A phrasing effect must beat both the no-note arm and each other.
    * length matching within +-10%, reported.
    * the outcome is read from the working-tree artifact, never from prose (1 run in v4
      and 2 in G0 said one thing and did another).
    * delivery surfaces fixed: HOUSE_STYLE.md (project file) + check.py output
      (tool-result channel), identical bytes.
    * pre-declared forced choice is retained (v4's design), and the structural cost of
      forcing a choice is estimated by comparing to G0 rather than assumed away.

  STOPPING RULE: if |P(UPDATE|H1) - P(UPDATE|H2)| < 0.30 then no phrasing effect is
  detectable at n=9/arm; report exactly that and stop. Do not add reps.

  EXPECTED DIRECTION null hypothesis: H1 == H2. If the two differ, wording matters.
  Cost ~$0.55.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


prior = load("rig_prior", HERE / "rig_prior.py")
arms = load("rig_arms", HERE / "rig_arms.py")
scorer = load("score_prior_from_artifact", HERE / "score_prior_from_artifact.py")
probe = prior.probe

RES = HERE / "results"
WORK = Path(r"D:\Project\_m4phrase")

H1 = (
    "House style: a rename is a breaking change. Update the call sites to the new name. "
    "Do not keep the old name working with an alias."
)
H2 = (
    "House style: a rename is usually treated as a breaking change here, so it may be "
    "worth updating the call sites to the new name instead."
)

ARMS = [("H1_IMPERATIVE", H1), ("H2_HEDGED", H2)]
REPS = 3
BASELINE = 4 / 9  # G0, scored from artifact


def main() -> int:
    RES.mkdir(parents=True, exist_ok=True)
    lens = {a: len(n) for a, n in ARMS}
    print("note lengths:", lens,
          "| spread", max(lens.values()) / min(lens.values()))
    rows = []
    n = 0
    for arm, note in ARMS:
        for idx in range(3):
            fx = prior.fixture(idx)
            for rep in range(1, REPS + 1):
                n += 1
                dest = WORK / f"ph{n}"
                arms.build_with_note(dest, fx, note)
                pre = prior.check_fails(dest, fx)
                if pre["rc"] == 0:
                    print(f"run {n} {arm}: fixture not broken -> discarded (no spend)")
                    probe.rmtree_force(dest)
                    continue
                note_out = "house style" in (pre["out"] or "").lower()
                rc, out, err, attempt = prior.run_agent(
                    dest, f"m4phrase{n}-{arm}-fx{idx + 1}-r{rep}")
                post = prior.check_fails(dest, fx)
                art = dict(run=n, arm=arm, fixture=idx + 1, rep=rep, note=note,
                           note_len=len(note), rc=rc, attempt=attempt,
                           harness_fail=not (out or "").strip(),
                           prose=prior.classify_choice(out),
                           note_delivered_in_check_output=note_out,
                           check_passed_after=(post["rc"] == 0),
                           old=fx["old"], new=fx["new"],
                           agent_tail=(out or "")[-1200:], wall_tail=(err or "")[-300:])
                try:
                    art["worktree_diff"] = probe.git(dest, "diff", "HEAD")[:20000]
                    art["git_status"] = probe.git(dest, "status", "--porcelain")
                    for ln in art["git_status"].splitlines():
                        if ln.startswith("??"):
                            rel = ln[3:].strip().strip('"')
                            fp = dest / rel
                            if fp.is_file() and fp.stat().st_size < 20000:
                                art.setdefault("untracked_contents", {})[rel] = \
                                    fp.read_text(encoding="utf-8", errors="replace")
                except Exception as exc:  # noqa: BLE001 — artifact loss must be visible
                    art["artifact_error"] = repr(exc)
                (RES / f"phrase{n}.json").write_text(
                    json.dumps(art, indent=1, ensure_ascii=False), encoding="utf-8")
                probe.rmtree_force(dest)
                rows.append(art)
                print(f"run {n} {arm} fx{idx + 1} r{rep}: prose={art['prose']:<10} "
                      f"check={art['check_passed_after']} note={note_out}")

    good = [r for r in rows if not r.get("harness_fail")]
    if not good:
        print("NO VALID RUNS — rig verdict, not a result. Exit 4.")
        return 4
    for r in good:
        r["artifact"], r["evidence"] = scorer.classify_from_patch(
            r.get("worktree_diff", ""), r.get("untracked_contents"),
            r["old"], r["new"])

    print("\n=== per-run, artifact-scored ===")
    for r in good:
        print(f"  run {r['run']:>2} {r['arm']:<14} fx{r['fixture']} r{r['rep']}: "
              f"prose={r['prose']:<10} artifact={r['artifact']:<9} {r['evidence']}")

    tally: dict[str, int] = {}
    for r in good:
        tally.setdefault(r["arm"], {}).setdefault(r["artifact"], 0)
        tally[r["arm"]][r["artifact"]] += 1

    p = {}
    for arm in ("H1_IMPERATIVE", "H2_HEDGED"):
        c = tally.get(arm, {})
        d = c.get("UPDATE", 0)
        u = c.get("PRESERVE", 0)
        tot = d + u
        p[arm] = d / tot if tot else float("nan")
        print(f"  {arm}: UPDATE={d} PRESERVE={u} "
              f"other={c.get('AMBIGUOUS', 0) + c.get('BOTH', 0)}  P(UPDATE)={p[arm]:.3f}")

    mism = [r for r in good if r["prose"] in ("UPDATE", "PRESERVE")
            and r["artifact"] in ("UPDATE", "PRESERVE") and r["prose"] != r["artifact"]]
    print(f"  prose-artifact mismatches: {len(mism)}/{len(good)} "
          f"(runs {[r['run'] for r in mism]})")
    print(f"  G0 no-note baseline P(UPDATE) = {BASELINE:.3f} (4/9)")

    if len(p) == 2:
        spread = abs(p["H1_IMPERATIVE"] - p["H2_HEDGED"])
        print(f"\n  |P(UPDATE|H1) - P(UPDATE|H2)| = {spread:.3f}  (threshold 0.30)")
        print(f"  H1 - baseline = {p['H1_IMPERATIVE'] - BASELINE:+.3f}")
        print(f"  H2 - baseline = {p['H2_HEDGED'] - BASELINE:+.3f}")
        if spread >= 0.30:
            print("GATE PASSED: phrasing itself moves the choice at controlled direction.")
        else:
            print("NO DETECTABLE PHRASING EFFECT at n=9/arm. Reporting as such.")
    else:
        print("only one arm valid — rig verdict, not a result. Exit 4.")
        return 4
    return 0


def selftest() -> int:
    """Zero-cost preflight. Must pass BEFORE any money is spent."""
    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg)
        ok = ok and cond

    lens = {a: len(n) for a, n in ARMS}
    check(max(lens.values()) / min(lens.values()) <= 1.10,
          f"note lengths matched {lens}")
    h1 = dict(ARMS)["H1_IMPERATIVE"]
    h2 = dict(ARMS)["H2_HEDGED"]
    check("Do not" in h1 or "Update the call sites." in h1, "H1 is imperative")
    check("may be" in h2 or "might" in h2, "H2 is hedged")
    check("Update the call sites" in h1 and "updating the call sites" in h2,
          "both arms point the SAME way (direction controlled)")
    check(BASELINE == 4 / 9, "baseline constant matches the measured G0 prior")
    print("SELFTEST:", "ALL PASS" if ok else "FAIL — do not spend")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys as _sys

    if "--selftest" in _sys.argv:
        _sys.exit(selftest())
    _sys.exit(main())