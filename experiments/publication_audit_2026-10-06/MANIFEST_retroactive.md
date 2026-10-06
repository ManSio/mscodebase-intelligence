# Claim list — RETROACTIVE, not a pre-registration

**Read this before using the file as a control.** This list was written on 2026-10-06, *after* the
claims below had already been published (dev.to article 4680630 comment threads, and GitHub issue
tjonesit/crystals#1) and after they had been read. It is therefore a **reconstruction of the published
claim set from the registries**, useful as the population for the audit in `RESULTS.md` — and useless
as evidence that the audit was predicted. Nothing here was frozen before a result was seen.

## Claims in the population

| id | claim as published | published at |
|---|---|---|
| C1 | arrival layer maps the dispositional symptom to family A in 5/5 runs, 2 valid, controls 6/6 | dev.to 3fej5 / Exp 23 |
| C2 | pinned regression valid 10/11, symptom → NONE in all runs | issue #1 |
| C3 | held-out F4b: arrival 10/11 vs symptom 3/11 | diary + `results/f4b/RESULTS.md` |
| C4 | regression on the recovered list: valid 5/11 | `results/recovered_e7/RESULTS.md` |
| C5 | reader stability "one model 8/10, another flipped 6/10" | dev.to 3feh2 / Exp 19 |
| C6 | "glm FA 0.24–0.38 vs qwen recall 0.08 → 0.88" | issue #1 |
| C7 | "recall 0.08 → 0.88 (×11)" | issue #1 |
| C8 | deterministic 1-V proxy ladder 1.0 / 0.12 / 0.16 / 0.24 | log |
| C9 | symptom → NONE in 10/10 valid runs of the original E7 | dev.to 3feh2 / Exp 19 |

## What the audit could not have been pre-registered against

C5, C6, C7 and C9 have **no surviving raw artifact in any form** — not in the working tree, not in any
of the 30 local and 30 remote branches, not in the three stashes, not in the reflog (complete back to
2026-07-31), not in 2,435 unreachable Zed checkpoint trees, and not among 4,650 unreachable blobs. For
those claims the only possible verdicts were CONFIRMED-by-luck or NOT RE-DERIVABLE, and they came out
the second way. A pre-registration could not have changed that; only committing raw output at run time
would have.
