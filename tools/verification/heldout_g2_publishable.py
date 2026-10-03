"""Frozen positive/negative controls for G2's PUBLISHABLE detector.

Every case is a real claim shape from our own records or from the primary sources
behind §19 (tjonesit's OpenWorkProof issue #2, our own experiment summaries). The
expectation is the point: a detector that cannot separate these has no power.

Provenance:
  - OpenWorkProof issue #2        -> "5.7 / 16.0 points, bar 10", "84 matches, 27 after"
  - tjonesit dev.to 4342586        -> "41 guards, 8 with a proven control, 0 broken, 33 unproven"
  - our vacuous scan (claims A11)  -> "1133 proven / 3 vacuous / 7 skip of 1143"
  - our G5 census (this session)   -> "755 candidates, 0 reviewed"
  - OpenWorkProof issue #2         -> "1106 matched, 193 delivered (18%)"
  - our claims audit                -> "2038 proven tests"

The negatives are as important as the positives (§7.1): ordinary prose containing
digits, and a process exit code, must NOT be treated as a published measurement.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates as g  # noqa: E402

CASES = [
    # (claim, expected verdict, provenance)
    ("5.7 / 16.0 points, bar 10", "BLOCK", "OpenWorkProof issue #2"),
    ("2038 proven tests", "BLOCK", "our claims audit A11"),
    ("1133 proven / 3 vacuous / 7 skip of 1143", "BLOCK", "our vacuous scan"),
    ("755 candidates, 0 reviewed", "BLOCK", "our G5 census"),
    ("1106 matched, 193 delivered (18%)", "BLOCK", "OpenWorkProof issue #2"),
    ("41 guards, 8 with a proven control, 0 broken, 33 unproven", "BLOCK", "dev.to 4342586"),
    ("84 matches, 27 after", "BLOCK", "OpenWorkProof issue #2"),
    ("1106 matched, 0 delivered, worst 39/0", "BLOCK", "OpenWorkProof issue #2"),
    ("coverage 100.0% achieved", "BLOCK", "our G5 first run"),
    ("gate suite rc=0, 9 steps OK", "BLOCK", "9 steps is a count; rc is stripped"),
    # negatives
    ("the run took 12 attempts in prose only", "ALLOW", "digit without a unit noun"),
    ("just some prose with no figures", "ALLOW", "no digits"),
    ("one paragraph of ordinary english with no digits", "ALLOW", "no digits"),
    ("7 of 10 benchmarks", "ALLOW", "a ratio of two counts, not a measurement"),
    ("the command exited cleanly", "ALLOW", "no number"),
]

# Every unit must be detected in BOTH singular and plural. Ordering bugs in the
# alternation silently killed 11 of these on the first attempt.
UNITS = ["test", "tests", "match", "matches", "item", "items", "check", "checks",
         "guard", "guards", "node", "nodes", "run", "runs", "claim", "claims",
         "case", "cases", "chunk", "chunks", "line", "lines", "experiment",
         "experiments", "cycle", "cycles", "finding", "findings", "candidate",
         "candidates", "step", "steps", "hit", "hits"]

results = []
print("=" * 100)
print("G2 PUBLISHABLE — frozen controls with provenance")
print("=" * 100)
print(f"{'verdict':<8} {'want':<8} claim")
print("-" * 100)
for claim, want, prov in CASES:
    r = g.g2_referent(claim=claim)
    ok = r["verdict"] == want
    results.append(ok)
    print(f"{r['verdict']:<8} {want:<8} {claim}")
    print(f"{'':<17} {prov}")
    if not ok:
        print(f"{'':<17} why: {r.get('why', '')[:100]}")

print()
print("-- unit detection, singular and plural")
missed = []
for u in UNITS:
    if g.g2_referent(claim=f"5 {u}")["verdict"] != "BLOCK":
        missed.append(u)
    if g.g2_referent(claim=f"5 {u} in the corpus")["verdict"] != "BLOCK":
        missed.append(u + " (in prose)")
ok = not missed
results.append(ok)
print(f"[{'OK ' if ok else 'XX '}] {len(UNITS) * 2} unit forms checked; "
      f"{len(missed)} missed{': ' + ', '.join(missed) if missed else ''}")

print()
print("=" * 100)
bad = results.count(False)
if bad:
    print(f"G2 CONTROLS FAILED: {bad} of {len(results)}")
    sys.exit(1)
print(f"G2 CONTROLS PASSED — {len(results)}/{len(results)}; "
      f"positives and negatives both present (§7.1)")
