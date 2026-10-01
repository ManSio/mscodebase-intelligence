"""RT6 held-out for G1-G4, on the REAL gate functions.

The built-in selftest proves each gate blocks for a stated reason. This proves
the sharper thing: a gate that blocks for a DIFFERENT reason does NOT pass.

Method: for every blocking case in gates.selftest(), inject a plausible
defect that should trip a *different* branch, and assert the reason changes.
A gate that keeps its old reason under a new defect is reason-blind.

Second axis — reason-blindness detector: feed a case whose `why` must change,
then assert the substring from the OLD reason is GONE. This is what catches a
gate that returns a canned string.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates as g  # noqa: E402

results = []
print("=" * 96)
print("RT6 HELD-OUT — G1..G4 must change their REASON when the defect changes")
print("=" * 96)


def check(name, res, must_contain, must_not_contain=()):
    why = (res.get("why") or "").lower()
    ok = must_contain.lower() in why
    for bad in must_not_contain:
        if bad.lower() in why:
            ok = False
            why += f"   <-- STALE REASON LEAKED: {bad!r}"
    results.append(ok)
    print(f"  [{'OK ' if ok else 'XX '}] {name}")
    print(f"        verdict={res.get('verdict')}  why={res.get('why')[:118]!r}")
    if not ok:
        print(f"        expected to contain {must_contain!r}; must NOT contain {list(must_not_contain)!r}")


# --- G1: empty-population block vs below-floor block are DIFFERENT reasons ------
r_empty, _ = g.run("population", population=0, computed_rate=0.0, label="vacuous scan")
r_floor, _ = g.run("population", population=91, computed_rate=0.0,
                   capacity_per_act=4000, corpus_size=108033, observed_horizon=6)
check("G1 empty population -> 'undefined'", r_empty, "population is 0", ("BLIND",))
check("G1 below floor -> 'BLIND, not healthy'", r_floor, "BLIND, not healthy", ("population is 0",))

# A floor that is met must NOT block. ceil(108033/4000) = 28, NOT 27 — a source
# published 27 by rounding down, which understates the floor by a whole cycle.
assert -(-108033 // 4000) == 28, "floor arithmetic changed"
r_below, _ = g.run("population", population=91, computed_rate=0.0,
                   capacity_per_act=4000, corpus_size=108033, observed_horizon=27)
check("G1 at 27 of a floor of 28 -> still BLIND", r_below, "floor 28 acts", ("population is 0",))
r_ok, _ = g.run("population", population=91, computed_rate=0.0,
                capacity_per_act=4000, corpus_size=108033, observed_horizon=28)
check("G1 at the floor -> ALLOW", r_ok, "population=91", ("BLIND",))

# --- G2: three distinct reasons, no leakage ------------------------------------
r_noref, _ = g.run("referent", claim="valid 10/11, controls 6/6")
r_super, _ = g.run("referent", claim="orphan wait 120ms, measured on 3798d6a9")
r_snap, _ = g.run("referent", claim="reranker score 5.7 points vs baseline, per `EXP-14`",
                  require_snapshot=True)
check("G2 no referent -> 'no referent'", r_noref, "with no referent", ("superseded", "content hash"))
check("G2 pinned -> 'superseded by'", r_super, "superseded by", ("no referent", "content hash"))
check("G2 snapshot -> 'content hash'", r_snap, "content hash", ("no referent", "superseded"))

# a claim WITH a snapshot must pass, proving the block was the snapshot's doing
r_snapok, _ = g.run("referent", claim="reranker score 5.7 points, snapshot sha256 7a3e2063, `EXP-14`",
                    require_snapshot=True)
check("G2 with a snapshot -> ALLOW", r_snapok, "referent(s)", ("content hash", "BLOCK"))

# --- G3: known-case vs held-out are different verdicts --------------------------
r_known, _ = g.run("generalization", verdict="CONFIRMED",
                   evidence="replayed on the same 16 frozen items; 5/5 was confirmation")
r_held, _ = g.run("generalization", verdict="CONFIRMED",
                  evidence="held-out fresh symptom list, disjoint, no overlap")
check("G3 known case -> BLOCK 'not generalization'", r_known, "not generalization", ("held-out evidence",))
check("G3 held-out -> ALLOW", r_held, "held-out evidence present", ("not generalization",))

# --- G4: three distinct reasons -------------------------------------------------
r_none, _ = g.run("control", experiment="e", negative_control_shown_failing=False, controls_required=2)
r_one, _ = g.run("control", experiment="e", negative_control_shown_failing=True, controls_required=1)
r_okc, _ = g.run("control", experiment="e", negative_control_shown_failing=True, controls_required=2)
check("G4 no failing control", r_none, "control can fail", ("at least 2",))
check("G4 single control", r_one, "at least 2 are required", ("control can fail",))
check("G4 proper pair -> ALLOW", r_okc, "negative one demonstrated failing",
      ("control can fail", "at least 2"))

# --- unknown input -> UNKNOWN, never ALLOW --------------------------------------
for action, kw, nm in (
    ("population", dict(population=None, computed_rate=None), "G1 missing inputs"),
    ("referent", dict(claim=""), "G2 empty claim"),
    ("generalization", dict(verdict="CONFIRMED", evidence="it worked"), "G3 no evidence shape"),
    ("control", dict(experiment="e", negative_control_shown_failing=None), "G4 unstated control"),
):
    res, rc = g.run(action, **kw)
    ok = res["verdict"] == g.UNKNOWN and rc == 2
    results.append(ok)
    print(f"  [{'OK ' if ok else 'XX '}] {nm} -> UNKNOWN (rc={rc})")
    print(f"        why={res.get('why')!r}")

print("=" * 96)
bad = results.count(False)
if bad:
    print(f"RT6 HELD-OUT FAILED: {bad} of {len(results)} checks did not distinguish the reason")
    sys.exit(1)
print(f"RT6 HELD-OUT PASSED — {len(results)}/{len(results)}: every gate names its OWN reason")
