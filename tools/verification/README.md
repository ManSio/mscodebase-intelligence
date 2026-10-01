# Verification gates

Five gates, each answering one question. Run everything:

```bash
python tools/verification/run_all.py
```

Exit `0` = every guard is provable and its own selftest passes. The suite fails if
any guard loses the ability to fail, which is the property that matters.

## The gates

| Gate | Question | File |
|---|---|---|
| G1 | is this rate over a population that can carry it, above its delivery floor? | `gates.py` |
| G2 | does every publishable number carry a re-checkable referent? | `gates.py` |
| G3 | does a `CONFIRMED` verdict rest on held-out, not replay, evidence? | `gates.py` |
| G4 | has a negative control been *demonstrated failing*? | `gates.py` |
| G5 | is every number-bearing artifact registered against a derived denominator? | `g5_denominator.py` |

## Rules this suite enforces on itself

**Silence is not consent.** `UNKNOWN` and `OUT_OF_SCOPE` are distinct from `ALLOW`.
Every verdict carries `scope` (what it does NOT judge) and `decisive_region` (where
it actually changes a decision) — see `heldout_rt8_scope.py`.

**A gate must fail for its OWN reason.** Asserting only on a verdict passes a gate
that blocks for the wrong reason. `heldout_rt6_reasons.py` proves the reason
*changes* when the defect changes and the previous reason does not leak.

**A held-out must be able to fail.** `heldout_g5.py` sabotages the gate in a temp
copy and requires the suite to notice. Three earlier versions of that file were
discarded because each mutated state that outlived the test — a corrupted manifest,
a snapshot taken from a dirty file, a gate sabotaged in place and restored with
the sabotaged text. All cases now run in their own temp directory.

**No author-absolute paths.** `heldout_relocation.py` greps for them and runs the
gates from an unrelated working directory. A guard that only works on the machine
that wrote it is not a guard.

**Exit codes mean what they say.** `0` pass · `1` block · `2` undeterminable ·
`3` G5 structural block. A missing dependency exits `2` and prints no number —
a smaller population would be a lie.

## What the numbers mean

G5 coverage is currently **0.00%** (0 of 753 candidates classified). That is the
honest reading, not a failure of the gate: `n_sig1` is derived by the scan rule,
`n_reviewed` is authored and only rises when a human classifies a candidate. The
two must never be merged — setting `n_reviewed = n_sig1` makes coverage return
100% by construction, which is the exact pathology the gate exists to catch.

This is one author, one rule, one population. It is **not** independent
verification: observable agreement between two checks of the same code does not
establish independence (see arXiv 2604.07650).

## Regenerating the manifest

```bash
python tools/verification/bootstrap_denominator_manifest.py
```

Do this after artifacts gain or lose numbers, and review the diff before
committing: the diff is a list of new claims nobody has classified yet.
