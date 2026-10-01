"""Held-out validation: run the gates against cases we KNOW are defective.

Fixtures prove a gate can block. This proves it blocks the right things —
the inputs are verbatim from our own records (2026-09-26..30) and from Tom's
correction, each already diagnosed by hand. If a gate waves one of these through,
the gate is decorative.

Expectation per row is written NEXT TO the case, so a disagreement is visible
without opening any other file.
"""
from __future__ import annotations

import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
# gates.py sits next to this file. Never an absolute machine path: this suite has to
# run in CI and on any clone, and a hardcoded developer path silently imports
# whatever happens to be on the author's machine instead of failing.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from gates import ALLOW, BLOCK, UNKNOWN, run  # noqa: E402

# (gate, kwargs, expected, provenance)
CASES = [
    ("G1 silent zero on an empty population",
     "population",
     dict(population=0, computed_rate=0.0, label="exp_vacuous_scan.py"),
     BLOCK,
     "KNOWN DEFECT: script hardcoded to a nonexistent experiments/tests; printed "
     "'0 proven / 0 vacuous, доля 0.0%' and exited rc=0"),

    ("G1 real zero on a non-empty population",
     "population",
     dict(population=1143, computed_rate=0.3, label="vacuous share, real corpus"),
     ALLOW,
     "legitimate: 3/1143 vacuous on a populated scan"),

    ("G1 real F4b arrival clean rate",
     "population",
     dict(population=11, computed_rate=10 / 11, label="F4b arrival"),
     ALLOW,
     "legitimate: 10 of 11 runs clean"),

    ("G2 our own published claim without a referent",
     "referent",
     dict(claim="Валид 10/11, контроли 6/6, #16 → NONE везде."),
     BLOCK,
     "our own E7 restatement — three publishable numbers, no file:line, no command"),

    ("G2 Tom's corrected figure without a referent",
     "referent",
     dict(claim="84 matches before the fix and 27 after, with all 57 silenced lines "
                "read by hand."),
     BLOCK,
     "his own retracted claim; not reproducible from his repo, and no referent given"),

    ("G2 our own claim WITH a referent",
     "referent",
     dict(claim="valid 10/11 per `results/pinned_variant/RESULTS.md:15`"),
     ALLOW,
     "legitimate: number plus file:line"),

    ("G2 a number pinned to a commit but never superseded",
     "referent",
     dict(claim="orphan wait 30s -> 120ms, measured on 3798d6a9"),
     BLOCK,
     "A10: the path was removed by design (R3TF 2026-08-26); a commit-pinned claim "
     "with no `superseded by` presents a dead number as current"),

    ("G2 the same claim once marked superseded",
     "referent",
     dict(claim="orphan wait 30s -> 120ms, measured on 3798d6a9, superseded by "
                "ORPHAN-removed in 7974d981"),
     ALLOW,
     "legitimate: dead number, honestly labelled"),

    ("G3 our F4b claim stated as generalization",
     "generalization",
     dict(verdict="CONFIRMED",
          evidence="5/5 совпадений по тем же 16 пунктам"),
     BLOCK,
     "the diary itself says '5/5 был confirmation, не generalization'"),

    ("G3 the same finding stated correctly",
     "generalization",
     dict(verdict="CONFIRMED",
          evidence="✅ confirmed on known case; ⚠️ not tested on new cases"),
     BLOCK,
     "still a replay — an explicit label does not turn a replay into generalization"),

    ("G3 a genuinely held-out claim",
     "generalization",
     dict(verdict="CONFIRMED",
          evidence="held-out F4b list, disjoint from the frozen list, no overlap"),
     ALLOW,
     "legitimate: fresh items, overlap gate passed"),

    ("G4 an experiment reported without a failing control",
     "control",
     dict(experiment="pinned_variant (E7 regression)",
          negative_control_shown_failing=None, controls_required=2),
     UNKNOWN,
     "we never demonstrated a control failing on that run — UNKNOWN must not be read as pass"),

    ("G4 an experiment with the control explicitly dismissed",
     "control",
     dict(experiment="pinned_variant (E7 regression)",
          negative_control_shown_failing=False, controls_required=2),
     BLOCK,
     "a control never seen failing certifies nothing"),

    ("G4 F4b, where a negative control WAS demonstrated",
     "control",
     dict(experiment="F4b", negative_control_shown_failing=True, controls_required=2),
     ALLOW,
     "legitimate: `scripts/f4b_validate.py --selftest` returns rc=1 on a generic answer"),

    ("G4 one control only",
     "control",
     dict(experiment="node-health scan", negative_control_shown_failing=True,
          controls_required=1),
     BLOCK,
     "a single control cannot be both the positive and the negative one"),

    # ---- cases taken from his OpenWorkProof issue #2 (2026-09-26), never in our thread ----
    ("G1 non-empty population but below the delivery floor",
     "population",
     dict(population=91, computed_rate=0.18, label="delivery rate",
          capacity_per_act=4000, corpus_size=108033, observed_horizon=3),
     BLOCK,
     "his case: corpus 108,033 chars / 4,000 per-act budget => floor 27 acts. Horizon 3 is "
     "below the floor, so 18% is unreadable — starvation and unreached are indistinguishable"),

    ("G1 same population once the horizon clears the floor",
     "population",
     dict(population=91, computed_rate=0.18, label="delivery rate",
          capacity_per_act=4000, corpus_size=108033, observed_horizon=91),
     ALLOW,
     "the same rate becomes readable once the observed horizon passes the floor"),

    ("G2 a score claim with no corpus hash",
     "referent",
     dict(claim="valid 10/11 on the catalogue, see `results/pinned_variant/RESULTS.md`",
          require_snapshot=True),
     BLOCK,
     "his rule: a score is a key cut for ONE snapshot; a claim without the hash is not "
     "re-checkable, and not-re-checkable defaults to unverified — not to true"),

    ("G2 a score claim carrying the snapshot hash",
     "referent",
     dict(claim="valid 10/11, catalogue sha256 8657a7e3949b5a3e", require_snapshot=True),
     ALLOW,
     "the same claim with the measured snapshot attached"),

    ("G2 a commit sha is NOT a corpus snapshot",
     "referent",
     dict(claim="21% recall, measured on 7974d981", require_snapshot=True),
     BLOCK,
     "our A7: the recorded sha256 of the frozen input did not reproduce byte-for-byte (CRLF) — "
     "the content moved under an unchanged commit"),
]


def main() -> int:
    print(f"{'case':46} {'gate':7} {'expect':9} {'got':9} {'ok':5}")
    print("-" * 92)
    ok = True
    for name, action, kw, expect, why in CASES:
        res, rc = run(action, **kw)
        got = res["verdict"]
        good = got == expect
        ok = ok and good
        print(f"{name:46} {res['gate']:7} {expect:9} {got:9} {'OK' if good else 'MISS':5}")
        if not good:
            print(f"      why: {res['why'][:110]}")
    print()
    print(f"{'provenance of each case':46}")
    for name, *_rest, why in CASES:
        print(f"  - {name}\n      {why}")
    print(f"\nHELD-OUT RESULT: {'PASSED — gates block what is actually broken' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
