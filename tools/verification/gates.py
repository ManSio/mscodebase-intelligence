"""gates.py — the enforcement layer of the agent protocol.

Why this exists, in the project's own evidence: three separate studies (arXiv
2601.20404, 2602.11988, 2607.27250) agree that prose in context does not convert
a near-miss into a pass. Khatri's manipulation probe is the sharp version: a real,
well-rated AGENTS.md never rescued a failing run on either agent. A rule that
cannot fail is a preference. These gates fail.

Design constraint from R6 (Anthropic): tool sets must not overlap. So there are
exactly FOUR checks with disjoint scope, exposed through ONE tool action, not
four tools.

    G1  POPULATION    a metric computed on an empty population is not a result
    G2  REFERENT      a number published without a referent is not a fact
    G3  GENERALIZATION a replay on known items is confirmation, not generalization
    G4  CONTROL       a verdict without a control shown to fail is untested

Exit codes: 0 = pass · 1 = violation (the gate BLOCKS) · 2 = unusable input
(loudly refuses to answer — per P-01: a silent zero is worse than a crash).

`--selftest` must prove every check can fail. A gate that cannot fail is worse
than no gate: it certifies the wrong set.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

BLOCK = "BLOCK"
ALLOW = "ALLOW"
UNKNOWN = "UNKNOWN"          # not enough input to judge -> must never read as ALLOW


# ---------------------------------------------------------------- G1 POPULATION
def g1_population(*, population: int | None, computed_rate: float | None,
                  label: str = "", capacity_per_act: int | None = None,
                  corpus_size: int | None = None,
                  observed_horizon: int | None = None) -> dict:
    """A rate over an EMPTY population is a lie dressed as a number.

    Extended by a measured reference case (tjonesit, OpenWorkProof issue #2, 2026-09-26):
    a NON-EMPTY population is still not enough. With corpus 108,033 chars against a
    4,000-char per-act budget the floor is 27 acts — below that horizon "stuck" and "not yet
    reached" are indistinguishable, so a 0% failure rate is unreadable. Non-re-checkable
    defaults to unverified, not to true. So when capacity/corpus/horizon are supplied, the
    gate also checks the floor.
    """
    if population is None or computed_rate is None:
        return {"gate": "G1", "verdict": UNKNOWN,
                "why": "population and/or rate not supplied — cannot judge"}
    if population <= 0:
        return {"gate": "G1", "verdict": BLOCK, "label": label,
                "why": f"population is {population}; the rate {computed_rate} is undefined "
                       "but would be printed as if it were a result"}

    # Floor check, when the numbers exist.
    # floor = ceil(corpus / capacity) — the minimum horizon at which EVERY item could
    # have been delivered once. Rounding down (as a published source did: 108033/4000
    # reported as "27 acts") understates the floor and lets a blind measurement through.
    floor = None
    if capacity_per_act and corpus_size:
        floor = -(-corpus_size // capacity_per_act)          # exact ceil
        if observed_horizon is not None and observed_horizon < floor:
            return {"gate": "G1", "verdict": BLOCK, "label": label,
                    "why": f"corpus {corpus_size} / budget {capacity_per_act} => floor {floor} acts; "
                           f"observed horizon was only {observed_horizon}. A 0% failure rate over "
                           f"that horizon is BLIND, not healthy — starvation and unreached are "
                           f"indistinguishable below the floor"}
    if computed_rate == 0.0 and population > 0:
        note = f" (floor {floor} acts)" if floor else ""
        return {"gate": "G1", "verdict": ALLOW, "label": label,
                "why": f"population={population}, rate=0.0 — a real zero on a non-empty set{note}"}
    tail = f", floor {floor} acts" if floor else ""
    return {"gate": "G1", "verdict": ALLOW, "label": label,
            "why": f"population={population}, rate={computed_rate}{tail}"}


# ------------------------------------------------------------------ G2 REFERENT
# a referent is: a command | a path:line | an EXP/KI/EXP id | "measured on <sha>"
REFERENT = re.compile(
    r"(`[^`]+`|[\w./-]+\.(?:py|md|ts|json|sh):\d+|\b(?:EXP|KI|P)-?\d+\b"
    r"|measured on\s+[0-9a-f]{7,40}|\bsha256\b|\bcommit\b)", re.IGNORECASE)
# a number that would be published. Learned the hard way: a first version matched only
# `%`, `N/M`, and time units, so it waved through "84 matches ... 27 after" — a bare count
# with a noun. Bare integers count ONLY with a unit noun or a range, else every sentence
# with a stray digit would block.
# ONE alternative per concept, with an explicit optional plural. Do NOT list both
# forms as separate alternatives: `test` before `tests` makes `test\b` match the first
# four chars of "tests", the trailing \b then fails, and the engine does not backtrack
# into the next alternative here — the unit silently stops matching. Found by
# heldout_rt8_scope.py; it affected test/tests, match/matches, item/items,
# check/checks, node/nodes, run/runs, claim/claims, case/cases, line/lines.
# An earlier "fix" that merely reordered the alternatives deleted the singulars and
# broke 11 units. Ordering is not the cure; collapsing the pair is.
UNIT_NOUN = (r"(?:match(?:es)?|ошиб\w+|раз|шт|item(?:s)?|finding(?:s)?|строк(?:и)?|"
             r"line(?:s)?|attack(?:s)?|ошибка|файл(?:ы)?|file(?:s)?|"
             r"запуск|run(?:s)?|progon|runov|прогон|note(?:s)?|замет\w+|кристалл(?:ов)?|"
             # FOUND BY heldout_rt6_reasons.py: a score in points with no other unit was
             # passing G2 unrestrained — "5.7 / 16.0 points, bar 10" is exactly the shape
             # tjonesit used in OpenWorkProof issue #2. `point` (singular) is deliberately
             # excluded: it collides with ordinary prose ("12 points of contention").
             r"points|pts|балл(?:а|ов|у)?|"
             # FOUND BY heldout_rt8_scope.py: "2038 proven tests" is OUR OWN published
             # claim (vacuous scan) and was not matched at all.
             r"test(?:s)?|assert(?:s)?|check(?:s)?|guard(?:s)?|chunk(?:s)?|"
             r"experiment(?:s)?|claim(?:s)?|case(?:s)?|node(?:s)?|cycle(?:s)?|"
             # FOUND BY heldout_rt8_scope.py: "755 candidates, 0 reviewed" and
             # "1133 proven / 3 vacuous / 7 skip of 1143" are our own published shapes.
             r"candidate(?:s)?|skip(?:s)?|step(?:s)?|hit(?:s)?|block(?:s)?|"
             r"node(?:s)?|file(?:s)?|variant(?:s)?|arm(?:s)?|"
             r"threshold|floor)")

# Shape: "<number> <modifier> <unit>" where the modifier is an adjective, not the unit.
# FOUND by heldout_rt8_scope.py: our own published claim "2038 proven tests" carries a
# word between the number and the unit, so the plain number+unit pattern missed it.
# MUST be a non-capturing GROUP. Without the `(?:...)` the `|` operators escape the
# repetition quantifier below and turn `\s+{0,2}` into a "multiple repeat" error, or
# silently bind the modifier to the wrong branch. Same trap as UNIT_NOUN below.
ADJ_MODIFIER = (r"(?:proven|proved|verified|confirmed|vacuous|unproven|eligible|included|"
                r"uncovered|covered|distinct|unique|valid|failing|passing|skipped|"
                r"total|raw|clean|real|sampled|seen|reviewed|of)")
# NOTE: every alternative is a bare word with NO trailing \s+. An earlier version put
# `\s+` inside the last alternative only, so the repetition quantifier demanded a
# second space and the whole class silently matched nothing.
UNIT_TAIL = re.compile(
    # The numeric class must END on a digit: `[\d ,._]*` also matches the trailing
    # space, which then leaves nothing for the mandatory `\s+` and silently fails.
    rf"(?<![\w.])\d+(?:[\d ,._]*\d)?\s*(?:%|x\b|×|k\b|MB|KB|ms|s\b)?\s+"
    rf"(?:{ADJ_MODIFIER}\s+){{0,2}}(?:{UNIT_NOUN})\b",
    re.IGNORECASE)

# A unit linked across a slash: "1133 proven / 3 vacuous / 7 skip of 1143".
# Each number carries its own unit; the pattern is number [modifier] / number [modifier].
SLASH_RUN = re.compile(
    rf"\d+(?:\s+(?:{ADJ_MODIFIER})\s+){{0,2}}(?:\s*(?:{UNIT_NOUN}))?"
    rf"(?:\s*[/of]\s*\d+(?:\s+(?:{ADJ_MODIFIER})\s+){{0,2}}(?:\s*(?:{UNIT_NOUN}))?)+",
    re.IGNORECASE)

# Two more shapes that are published claims and were silently unmatched:
#   "5.7 / 16.0 points"   -> only the right-hand number matched, the left was dropped
#   "84 matches ... 27 after" -> only the FIRST matched
PUBLISHABLE_EXTRA = re.compile(
    # a decimal head immediately before a unit-bearing decimal or a slash-range
    rf"(?<![\w.])\d+\.\d+(?=\s*(?:/|{UNIT_NOUN}))"
    # a range: "84 ... 27 after", "1106 matched, 193 delivered"
    rf"|(?<![\w.])\d+(?=\s*(?:\.\.\.|,|to|→|->|и|до)\s*\d+\s*(?:{UNIT_NOUN}|after|из|of))",
    re.IGNORECASE)
# "rc=0", "rc=2", "exit 1" — a process status, NOT a measurement. Counting it made
# `gate suite rc=0, 9 steps OK` a publishable claim (false alarm), because `0` sits
# right before `steps`. Stripped before the number scan.
RC_TOKEN = re.compile(r"\b(?:rc|exit\s*code|returncode|status)\s*[=:]\s*-?\d+", re.IGNORECASE)
PUBLISHABLE = re.compile(
    rf"(\d+(?:\.\d+)?\s?%|\b\d+/\d+\b|\d+(?:\.\d+)?\s?(?:ms|s\b|sec|minutes|min|hours|ч\b|мин\b)"
    rf"|\b\d+(?:\.\d+)?\s?[KkMm]\b"
    rf"|\b\d+(?:\.\d+)?\s+{UNIT_NOUN}"
    rf"|\b\d+(?:\.\d+)?\s*(?:to|→|->|и|до)\s*\d+)",
    re.IGNORECASE)


def g2_referent(*, claim: str, require_reproducible: bool = True,
                require_snapshot: bool = False) -> dict:
    """Every publishable number needs a referent that can be re-checked today.

    `require_snapshot` encodes the sharpest form of the rule we have found, from Tom Jones's
    starter kit (2026-07): "a score claim that doesn't carry the hash it was measured against
    is not re-checkable, and not-re-checkable defaults to unverified — not to true." A commit
    sha is not enough; the thing measured changes underneath it.
    """
    if not claim or not claim.strip():
        return {"gate": "G2", "verdict": UNKNOWN, "why": "empty claim"}
    # a process exit code is not a published measurement — see RC_TOKEN
    scannable = RC_TOKEN.sub(" ", claim)
    nums = [m if isinstance(m, str) else next(x for x in m if x)
            for m in PUBLISHABLE.findall(scannable)]
    nums += [m for m in PUBLISHABLE_EXTRA.findall(claim) if m not in nums]
    nums += [m for m in UNIT_TAIL.findall(claim) if m not in nums]
    nums += [m for m in SLASH_RUN.findall(claim) if m not in nums]
    if not nums:
        return {"gate": "G2", "verdict": ALLOW,
                "why": "no publishable number in the claim"}
    refs = REFERENT.findall(claim)
    if not refs:
        return {"gate": "G2", "verdict": BLOCK,
                "why": f"{len(nums)} publishable number(s) ({', '.join(nums[:3])}) with no referent — "
                       "no command, no file:line, no EXP/KI id, no sha"}
    if require_reproducible and re.search(r"measured on\s+[0-9a-f]{7,40}", claim, re.I) \
            and not re.search(r"superseded by", claim, re.I):
        return {"gate": "G2", "verdict": BLOCK,
                "why": "claim is pinned to a commit but has no `superseded by ...` — "
                       "a dead number presented as current"}
    if require_snapshot and not re.search(r"(sha256|content hash|hash[: ]|снимок|снапшот|"
                                           r"snapshot|digest|@[0-9a-f]{7,40})", claim, re.I):
        return {"gate": "G2", "verdict": BLOCK,
                "why": f"{len(nums)} score-bearing number(s) with no content hash / snapshot of the "
                       "corpus it was measured against — a score is a key cut for ONE snapshot, and "
                       "a claim that cannot be re-checked defaults to unverified, not to true"}
    return {"gate": "G2", "verdict": ALLOW,
            "why": f"{len(nums)} number(s), {len(refs)} referent(s)"}


# ------------------------------------------------------------- G3 GENERALIZATION
HELD_OUT = re.compile(r"held[- ]?out|holdout|heldout|new items|свежий|свежие|не пересека|"
                      r"disjoint|no overlap|out[- ]of[- ]domain", re.I)
# Real phrasings observed in our own records, not invented ones: "на тех же 16 frozen-пунктах",
# "повтор на известном кейсе", "same 16 items as the original run", "5/5 was confirmation".
KNOWN_CASE = re.compile(
    r"known case|replay|re-?run|regression|confirmation|"
    r"the same|same \d+|frozen (items|list|item|symptoms|правил)|"
    r"по тем же|по тем же|по тому же|на тех же|тем же (пункт|списк|кейс|набор)|"
    r"тот же (кейс|список|набор)|повтор|"
    r"подтверждение (на том же)|= confirmation|не generalization|повторов", re.I)


def g3_generalization(*, verdict: str, evidence: str) -> dict:
    """"It works" proved on the case where the bug was found is confirmation, not
    generalization. Refusing the word is the whole point."""
    v = (verdict or "").upper()
    if "CONFIRM" in v or "ПОДТВЕРЖ" in (verdict or "").upper():
        if HELD_OUT.search(evidence or ""):
            return {"gate": "G3", "verdict": ALLOW,
                    "why": "held-out evidence present"}
        if KNOWN_CASE.search(evidence or ""):
            return {"gate": "G3", "verdict": BLOCK,
                    "why": "verdict says confirmed, but the evidence is a replay on the known "
                           "case — that is `✅ confirmed on known case`, not generalization"}
        return {"gate": "G3", "verdict": UNKNOWN,
                "why": "verdict claims confirmation; supply held-out or known-case evidence"}
    return {"gate": "G3", "verdict": ALLOW, "why": f"verdict {v!r} makes no generalization claim"}


# -------------------------------------------------------------------- G4 CONTROL
CONTROL_FAILS = re.compile(r"negative control|негативн\w+ контрол|control.{0,20}(failed|"
                           r"fell|fired|провал|упал)|--selftest|rc=1|control is discriminating",
                           re.IGNORECASE)


def g4_control(*, experiment: str, negative_control_shown_failing: bool | None,
               controls_required: int = 2) -> dict:
    """A control that has never been seen to FAIL has not been shown to work."""
    if negative_control_shown_failing is None:
        return {"gate": "G4", "verdict": UNKNOWN,
                "why": "was not told whether a control was shown failing"}
    if not negative_control_shown_failing:
        return {"gate": "G4", "verdict": BLOCK,
                "why": f"experiment {experiment!r} was reported without demonstrating that a "
                       "control can fail — a control that cannot fail certifies nothing"}
    if controls_required < 2:
        return {"gate": "G4", "verdict": BLOCK,
                "why": f"{controls_required} control(s): at least 2 are required — one must be "
                       "expected to FAIL (negative) and one expected to pass (positive)"}
    return {"gate": "G4", "verdict": ALLOW,
            "why": f"{controls_required} controls, a negative one demonstrated failing"}


GATES = {
    "population": g1_population,
    "referent": g2_referent,
    "generalization": g3_generalization,
    "control": g4_control,
}

# ------------------------------------------------------------------ RT8: SCOPE
# Source: arXiv 2608.06940 — verification changes a label only in the PIVOTAL
# region; outside it an aggregate statistic "can obscure a reliable conditional
# effect". So a verdict must declare where it is decisive and where it is silent.
#
# Every gate below states, in one line, what it does NOT judge. A caller that
# supplies `in_scope=False` gets OUT_OF_SCOPE, never ALLOW — because "this gate
# does not apply" and "this gate passed" are different claims, and conflating
# them is how an unchecked region reads as a clean bill of health.
OUT_OF_SCOPE = "OUT_OF_SCOPE"
SCOPE = {
    "G1": ("judges the DENOMINATOR and the delivery floor of a rate. It does NOT judge "
           "whether the measured quantity is the right thing to measure, nor the sample."),
    "G2": ("judges whether a publishable number carries a re-checkable referent. It does NOT "
           "judge whether the number is CORRECT, nor whether the referent is honest."),
    "G3": ("judges whether a 'confirmed' verdict rests on held-out rather than known-case "
           "evidence. It does NOT judge the sample size or the effect size."),
    "G4": ("judges whether a negative control has been DEMONSTRATED failing. It does NOT judge "
           "whether that control is the right control for this failure mode."),
    "G5": ("judges whether every number-bearing artifact is registered with its count. It does NOT "
           "judge whether any candidate number is TRUE."),
}

# Where the verdict actually changes a decision. Outside this region the gate is
# SILENT, and silence is not consent (musubi runbook: "a rule that never matches
# is indistinguishable from a rule that never had cause to").
DECISIVE = {
    "G1": ("decisive only when population == 0, or observed_horizon < ceil(corpus/capacity). "
           "In between it restates the rate and adds no information."),
    "G2": ("decisive only for claims whose numbers match PUBLISHABLE. A number outside that "
           "class is not examined at all — the gate is silent, not passing."),
    "G3": ("decisive only for verdicts containing CONFIRM. For any other verdict word it "
           "returns ALLOW because it makes no generalization claim — that is silence."),
    "G4": ("decisive only when the caller actually knows whether a control was shown failing. "
           "UNKNOWN there means the gate did not look."),
}


def scope_of(gate: str) -> str:
    return SCOPE.get(gate, "scope undeclared — treat this verdict as untrustworthy")


def run(action: str, *, in_scope: bool = True, **kw) -> tuple[dict, int]:
    fn = GATES.get(action)
    if fn is None:
        return ({"gate": action, "verdict": UNKNOWN, "scope": "unknown gate",
                 "why": f"unknown gate {action!r}; known: {sorted(GATES)}"}, 2)
    if not in_scope:
        # RT8: a gate that does not apply must not return ALLOW. It must say so.
        gname = {"population": "G1", "referent": "G2",
                 "generalization": "G3", "control": "G4"}.get(action, action.upper())
        return ({"gate": gname, "verdict": OUT_OF_SCOPE,
                 "scope": scope_of(gname),
                 "decisive_region": DECISIVE.get(gname, "undeclared"),
                 "why": "caller declared this input outside the gate's applicability; "
                        "no verdict was reached. OUTSIDE ITS SCOPE IS NOT A PASS."}, 0)
    res = fn(**kw)
    gname = res.get("gate", action)
    res["scope"] = scope_of(gname)
    res["decisive_region"] = DECISIVE.get(gname, "undeclared")
    rc = {"BLOCK": 1, "ALLOW": 0, "UNKNOWN": 2, OUT_OF_SCOPE: 0}[res["verdict"]]
    return res, rc


# ---------------------------------------------------------------------- selftest
# RT6: a gate that blocks FOR THE WRONG REASON passes a verdict-only selftest.
# Source: ICSE "To Kill a Mutant" — a mutant counts as killed regardless of why
# the suite failed, and a suite with no assertions kills >50% of mutants. So
# every case below declares the REASON it must block for, and the selftest
# asserts that exact substring appears in the gate's own `why`.
def selftest() -> int:
    """Every gate must be able to block — FOR THE REASON IT CLAIMS."""
    # (name, action, kwargs, expected_verdict, required substring in `why`)
    cases = [
        ("G1 empty population blocks",
         "population", dict(population=0, computed_rate=0.0, label="vacuous scan"),
         BLOCK, "population is 0"),
        ("G1 real zero on non-empty set is allowed",
         "population", dict(population=1143, computed_rate=0.0),
         ALLOW, "real zero on a non-empty set"),
        ("G1 missing inputs -> UNKNOWN not ALLOW",
         "population", dict(population=None, computed_rate=None),
         UNKNOWN, "not supplied"),
        ("G1 below the delivery floor is BLIND, not healthy",
         "population", dict(population=91, computed_rate=0.0, capacity_per_act=4000,
                            corpus_size=108033, observed_horizon=6),
         BLOCK, "BLIND, not healthy"),
        ("G1 a floor rounded DOWN by one is still below it",
         "population", dict(population=91, computed_rate=0.0, capacity_per_act=4000,
                            corpus_size=108033, observed_horizon=27),
         BLOCK, "floor 28 acts"),
        ("G2 number with no referent",
         "referent", dict(claim="valid 10/11, controls 6/6"),
         BLOCK, "with no referent"),
        ("G2 number with a referent",
         "referent", dict(claim="valid 10/11 per `EXPERIMENTS_LOG.md:537`"),
         ALLOW, "1 referent(s)"),
        ("G2 pinned claim with no superseded-by",
         "referent", dict(claim="orphan wait 120ms, measured on 3798d6a9"),
         BLOCK, "superseded by"),
        ("G2 score without a snapshot hash",
         "referent", dict(claim="reranker score 5.7 points vs baseline, per `EXP-14`",
                          require_snapshot=True),
         BLOCK, "content hash"),
        ("G2 'points' is a publishable unit (found by held-out: it was not)",
         "referent", dict(claim="5.7 / 16.0 points, bar 10, inconclusive"),
         BLOCK, "with no referent"),
        ("G3 confirmed but replayed on the known case",
         "generalization", dict(verdict="CONFIRMED",
                                evidence="replayed on the same 16 frozen items as the original "
                                         "run; 5/5 was confirmation, not generalization"),
         BLOCK, "not generalization"),
        ("G3 confirmed on a fresh held-out list",
         "generalization", dict(verdict="CONFIRMED",
                                evidence="held-out fresh symptom list, disjoint, no overlap"),
         ALLOW, "held-out evidence present"),
        ("G3 confirmation claim with no evidence shape",
         "generalization", dict(verdict="CONFIRMED", evidence="it worked"),
         UNKNOWN, "supply held-out or known-case evidence"),
        ("G4 experiment with no failing control",
         "control", dict(experiment="pinned_variant",
                         negative_control_shown_failing=False, controls_required=2),
         BLOCK, "control can fail"),
        ("G4 single control is not enough",
         "control", dict(experiment="x", negative_control_shown_failing=True, controls_required=1),
         BLOCK, "at least 2 are required"),
        ("G4 with a demonstrated failing control",
         "control", dict(experiment="pinned_variant",
                         negative_control_shown_failing=True, controls_required=2),
         ALLOW, "negative one demonstrated failing"),
    ]

    ok = True
    print(f"{'case':<48} {'want':<8} {'got':<8} {'verdict':<9} {'reason'}")
    print("-" * 100)
    for name, action, kw, want, needle in cases:
        res, _ = run(action, **kw)
        why = res.get("why", "") or ""
        v_ok = res["verdict"] == want
        r_ok = needle.lower() in why.lower()
        if not (v_ok and r_ok):
            ok = False
        print(f"{name:<48} {want:<8} {res['verdict']:<8} "
              f"{'OK' if v_ok else 'WRONG':<9} {'OK' if r_ok else 'WRONG REASON'}")
        if not r_ok:
            print(f"    required substring: {needle!r}")
            print(f"    actual why       : {why[:150]!r}")

    res, rc = run("nonexistent_gate")
    rc_ok = rc == 2
    if not rc_ok:
        ok = False
    print(f"{'unknown gate exits rc=2':<48} {'2':<8} {rc:<8} {'OK' if rc_ok else 'WRONG':<9} -")

    if ok:
        print("\nSELFTEST PASSED — gates can block, and each blocks for its OWN stated reason")
    else:
        print("\nSELFTEST FAILED — a gate blocked for the wrong reason, or did not block")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--gate", choices=sorted(GATES))
    ap.add_argument("--input", help="JSON object of kwargs")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.gate:
        ap.error("--gate is required (or --selftest)")
    try:
        kw = json.loads(args.input or "{}")
    except json.JSONDecodeError as e:
        print(json.dumps({"gate": args.gate, "verdict": UNKNOWN,
                          "why": f"bad JSON input: {e}"}, ensure_ascii=False))
        return 2
    res, rc = run(args.gate, **kw)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise SystemExit(2)
