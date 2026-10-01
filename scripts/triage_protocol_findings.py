"""TRIAGE of the protocol-guard findings — hand-adjudicated, evidence-first.

Why: the guard reported "8 finding(s)". Under §19.5 that is not a verdict until
the false-positive share is measured. Under §19.3 a control must be able to fail.

TWO attempts were made to automate this and BOTH were rejected, and the
rejections are the useful part:

  attempt 1 (keyword scan for "rate"/"%"):  classified 3 of 7 rate-tools as
    FALSE_POSITIVE because the WORD appeared only in prose — and produced
    UNRESOLVED for the rest. Better, but it was judging by vocabulary.

  attempt 2 (regex for division / percentage): claimed 7 TRUE_POSITIVE and
    cited `full_path = REPO_ROOT / rel_path` as an unguarded rate site. The `/`
    in a filesystem path is not a division. That verdict was FALSE by
    construction and it would have shipped as "7 confirmed defects".

So every row below is adjudicated by reading the actual rate computation and
recording the exact line, the denominator expression, and whether IT can be
zero on a reachable path. Nothing is inferred from a file name.

Guard (19.6/T10): empty finding population -> exit 2. No silent "0 defects".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]

# Each row was read by hand. `line` is 1-indexed and was re-verified before commit.
# `denom` is the literal denominator expression. `zero_ok` = can it be 0 reachable?
T10_ROWS = [
    {
        "rel": "scripts/e2e_quality_search.py",
        "desc": "live E2E search quality: hit@1 / hit@5 percentages",
        "line": 147,
        "denom": "n, where n = len(rows) (line 137)",
        "zero_ok": "yes — run_mode() returns [] when every search returns nothing",
        "verdict": "TRUE_POSITIVE",
        "reason": "hit@1/hit@5 are computed as 100*h1/n with no guard on n==0; "
                  "an empty row set raises ZeroDivisionError rather than a diagnosable "
                  "exit(2). Note line 146 DOES guard avg_ms with max(...,1) — so the "
                  "defence exists in this file but was not applied to the percentages.",
    },
    {
        "rel": "experiments/context_engine/compose_eval.py",
        "desc": "fraction of retained tokens that are wrong",
        "line": 64,
        "denom": "total = needed + wrong, over sections with t != 0",
        "zero_ok": "yes — wrong_ratio([]) returns 0.0",
        "verdict": "PARTIAL",
        "reason": "the ternary `wrong / total if total else 0.0` DOES guard the "
                  "division, but the fallback 0.0 is the PERFECT score. On an empty "
                  "population it reports an ideal result instead of refusing. This is "
                  "worse than a crash: it is a plausible false PASS.",
    },
    {
        "rel": "experiments/root_cause_eval/evaluate_root_cause.py",
        "desc": "mean similarity and mean latency over results",
        "line": 152,
        "denom": "max(total, 1) where total = len(results)",
        "zero_ok": "guarded",
        "verdict": "FALSE_POSITIVE",
        "reason": "both means use max(total, 1). The guard is present. The "
                  "guard's keyword scan saw the division and missed the max().",
    },
    {
        "rel": "experiments/noderag/run_experiment.py",
        "desc": "NodeRAG arm A vs arm B retrieval comparison",
        "line": 384,
        "denom": "sum(1 for r in rule_results if ...) — a COUNT, not a ratio",
        "zero_ok": "n/a",
        "verdict": "FALSE_POSITIVE",
        "reason": "lines 384-385 compute counts (a_hits, b_hits) and print them; no "
                  "percentage is derived from a possibly-empty denominator at this "
                  "site. No silent zero here.",
    },
    {
        "rel": "experiments/1V_memory_contamination/burst_sweep_exp.py",
        "desc": "burst memory-contamination sweep",
        "line": None,
        "denom": "no rate computation found",
        "zero_ok": "n/a",
        "verdict": "FALSE_POSITIVE",
        "reason": "the file writes modules, runs subprocesses and collects rows; it "
                  "computes no percentage or mean. T10 does not apply.",
    },
    {
        "rel": "experiments/bootstrap/tarantula_analysis2.py",
        "desc": "dependency analysis",
        "line": None,
        "denom": "no rate computation found",
        "zero_ok": "n/a",
        "verdict": "FALSE_POSITIVE",
        "reason": "builds a dependency graph and prints edges; no rate.",
    },
    {
        "rel": "experiments/evalmut/probe_evalmut_transfer.py",
        "desc": "mutation-transfer probe; total = len(rows) at line 138",
        "line": 138,
        "denom": "total = len(rows) — used for a rate? verified: no",
        "zero_ok": "n/a",
        "verdict": "FALSE_POSITIVE",
        "reason": "the probe's own design intentionally exercises the EMPTY case "
                  "(lines 125,127 probe('empty', ...)). total is used for iteration "
                  "and reporting, and the file already handles the empty input it "
                  "designed for. Flagging it as an unguarded rate is wrong.",
    },
]

T11_ROWS = [
    {
        "rel": "experiments/4A_unit_of_return/frozen/e7_HANDOUT_EN.recovered.md",
        "desc": "frozen handout, traceability fields",
        "missing": ["sha256", "command", "verdict"],
        "verdict": "TRUE_POSITIVE",
        "reason": "the artifact carries a claim-mapping table but no sha256, no "
                  "command, and no verdict field. It is a frozen input for an "
                  "experiment, so §17 requires it to be hash-addressable.",
    },
]

T12_ROWS = []  # §19.1 falsifiable hypotheses: 0 without the field -> no finding


def main() -> int:
    rows = [dict(r, rule="T10") for r in T10_ROWS] + [dict(r, rule="T11") for r in T11_ROWS]
    rows += [dict(r, rule="T12") for r in T12_ROWS]
    if not rows:
        print("FINDING POPULATION EMPTY -> no triage possible (silent zero, §19.6/T10)")
        return 2

    print("=" * 100)
    print("TRIAGE — hand-adjudicated, evidence-first. The guard still reports all findings;")
    print("this adds a verdict and the exact line it rests on.")
    print("=" * 100)
    for r in rows:
        print()
        print(f"{r['verdict']:<15} [{r['rule']}] {r['rel']}")
        print(f"{'':<15}   what    : {r['desc']}")
        if r.get("line"):
            print(f"{'':<17}   line    : {r['line']}")
            print(f"{'':<17}   denom   : {r['denom']}")
            print(f"{'':<17}   zeroable: {r['zero_ok']}")
        if r.get("missing"):
            print(f"{'':<17}   missing : {', '.join(r['missing'])}")
        print(f"{'':<17}   reason  : {r['reason']}")

    print()
    print("-" * 100)
    tally: dict[str, int] = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    total = len(rows)
    print(f"FINDINGS TRIAGED: {total}")
    for k in ("TRUE_POSITIVE", "PARTIAL", "FALSE_POSITIVE", "UNRESOLVED"):
        if k in tally:
            print(f"  {k:<15} {tally[k]}/{total} = {tally[k] / total * 100:.1f}%")
    actionable = tally.get("TRUE_POSITIVE", 0) + tally.get("PARTIAL", 0)
    print()
    print(f"MEASURED FALSE-POSITIVE SHARE: {tally.get('FALSE_POSITIVE', 0) / total * 100:.1f}%"
          f"  (guard reported {total}; {tally.get('FALSE_POSITIVE', 0)} were noise)")
    print(f"ACTIONABLE DEFECTS: {actionable} of {total}")
    print()
    print("REJECTED AUTOMATION (kept here so it is not retried):")
    print("  - keyword scan for 'rate'/'%'      -> 3 false negatives on guarded files")
    print("  - regex for division / percentage  -> cited filesystem paths as rate sites")
    print("Both verdicts were wrong in opposite directions. Neither may be used again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
