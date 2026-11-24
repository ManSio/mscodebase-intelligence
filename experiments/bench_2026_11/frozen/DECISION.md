# Decision record — which split counts for which bar

**Written:** 2026-11-15, before any further run. **Status:** binding for the next run.
**Why it exists:** two readers of the published write-up asked which result counts as
pre-registered after the November fix cycle. The answer has to be written down before
the next run, not chosen after it.

## What the frozen plan says

`frozen/PLAN.md` § Predictions:

| # | Prediction | Split |
|---|---|---|
| P1 | `hit@5` >= 0.35 | **dev** |
| P2 | tool `hit@5` >= grep `hit@5` + 5 tasks | dev |
| P3 | `any@8` >= `hit@5` on every bucket | all |
| P4 | sealed `hit@5` within +/- 0.10 of dev | **sealed** |

## What changed after the plan was written

The four gate defects were found by looking at dev and at `sqlalchemy`, and the fixes were
selected from that view. `REPORT.md` already records the consequence: "One run per split:
dev was re-run after Amendment 3, sealed was not."

After 11 November, dev is a **design set**, not a test set.

## Decision

1. The 10 November dev result (`19/71 = 0.268`, P1 FAIL) stands as the last pre-registered
   P1 measurement. It describes the code before the fixes.
2. The post-fix dev result (`38/71 = 0.535`) is reported as a **design-set measurement**.
   It clears 0.35 arithmetically and does not re-establish P1, because the fix was chosen
   after seeing dev.
3. The next result that may be called pre-registered is the **sealed** split, reported as
   **P4** (band +/-0.10 of the design-set dev number), `n = 37` solvable, run once, with the
   code revision recorded here before the run.
4. Sealed is **not** opened yet. Until it is, no sentence of the article may claim P1 passes.

## Rule that outlives this decision

A split used to design a fix cannot afterwards be reported as a pre-registered test. If one
panel must serve both roles, the design set and the test set are different splits, and the
test split runs once.

## Reporting rule (for the sealed run)

- Report the sealed outcome as **direction plus a 95% Wilson interval** over n=37; never the ratio alone.
- A **threshold pass is the worst case**: 13/37 = 0.351, lower bound **0.218**. Print that bound next to
  the 0.35 bar so a pass is not read as clearing it. The bound moves with the result:
  17/37 → [0.310, 0.616], 21/37 → [0.409, 0.713].
- State **"one run, no repeat by design"**: there is no second draw to narrow the interval.
- Cite this file by its commit in `main` (`3ec3052` created it, `e24ad59` last touched it) so a reader
  can check it predates the run.

## What does not reopen the design set

`d37b796` and `e24ad59` add reporting guards (`executed=` counter, replay refusal, foreign/missing row
refusal, provenance stamp). They change what the harness refuses to print, not which rows retrieval
returns, so they do not move the numbers and do not restart the cycle.

## What would change this

A sealed run executed before any further change to the retrieval gate, with its revision
recorded below. Anything else keeps this file as the current decision.

| run | split | revision | n | result |
|---|---|---|---|---|
| _(none yet)_ | sealed | — | 37 | — |
