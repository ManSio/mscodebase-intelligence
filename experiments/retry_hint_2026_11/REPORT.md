# E69 — retry hint (option C): result

Frozen: `frozen/PLAN.md`. Owner decision: keep `abstain`, make the continuation
explicit instead of prose.

## Change

When the gate withholds rows, the answer ends with:

```
Neighbours withheld: 8 (unverified).
next: investigate(query="...", include_neighbours=true, limit=8)
```

`ask_rewrite` carries the same shape with `hints=["<identifier>"]`. No row is
added to the default answer; the verdict stays `abstain`.

## Measurement (B1 dev, 71 solvable tasks)

```
hint emitted            36/71   (every abstain)
default hit@5           19/71   (E68 baseline: 19)
recovered by hint       18/36
default + hint total    37/71   [0.41, 0.63]   (E68 neighbours arm: 38)
```

Frozen predictions:

| # | Prediction | Result |
|---|---|---|
| R1 | default stays 19/71 | **PASS** — no rows leaked |
| R2 | every withheld answer carries the hint | **PASS** — 36/36 |
| R3 | default + hint >= 36/71 | **PASS** — 37 |

The one-task gap to the neighbours arm (37 vs 38) is the `abstain` task that
`include_neighbours` would answer and the default path scores differently; it is
inside the interval.

## A metric bug caught before publishing

The first run printed "after hint = 18/71" and failed R3. That was the metric,
not the product: 18 is the count *among the 36 hinted tasks*, and the other 35
were counted as misses even though the default had already answered them. The
correct panel-level number is `default + recovered = 37`. The threshold was not
changed; the metric was fixed, and an assertion now enforces that every hinted
task has `default hit@5 = False` (otherwise the sum would double-count).

## What C still does not do

The default answer remains empty on those 36 tasks. Recovering them requires the
caller to act on the `next:` line — that is the contract of option C, and it is
why the hint is machine-readable rather than a sentence. A host that ignores it
sees the same 19/71 as before, which is exactly what R1 measures.
