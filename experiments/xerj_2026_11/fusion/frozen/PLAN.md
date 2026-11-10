# Fusion A/B — frozen plan (before the run)

Date: 2026-11-10. Question: does the merge formula's channel weight dominate the
per-channel rank so much that ordering inside a channel stops mattering?

Current formula (`investigate_tool._merge`): `rank = score + weight`, where
`score` is the channel's rank score (`1/(idx+1)`, bounded by 1.0) and `weight`
is 0.3-2.5. Measured fact behind the question: the weight is 5-8x the rank term
for the top hits, and five XERJ ranking misses (P07, P09, P10, P12, T4) have a
correct declaration at ranks 2-8 behind same-name rows.

Arms (same panel, one process, interleaved, 3 repeats, per-task majority):

- **A — current**: `rank = score + weight`.
- **B — pure RRF**: `rank = Σ_c 1/(60 + idx_c)` over the channels that found
  the row (Cormack et al., SIGIR 2009), no hand weights.
- **C — normalized**: `rank = 0.5 * score + 0.5 * (weight / max_weight)` so both
  terms live in [0, 1]. A calibration arm, not a new doctrine.

Panels: XERJ 24 + mcp_audit 17 + metamorphic 12 (the last one is the one that
distinguishes "form" from "ranking").

Predictions (frozen):

| # | Prediction | Expected | Falsifier |
|---|---|---|---|
| F1 | B (RRF) does not lose `any@8` on XERJ or mcp_audit | PASS | any bucket loses a task |
| F2 | B improves `top1` by >= 2 tasks on the combined panel | PASS | `top1` gain <= 1 task |
| F3 | C does not beat B on `top1` | PASS | C > B by >= 2 tasks |
| F4 | no negative task gains a row | PASS | any negative row appears |
| F5 | latency of B is within +0.05 s of A | PASS | above |

Kill: F1 or F4 fails -> keep A. If F2 fails (gain <= 1 task), the weights are
not the binding constraint and the next lever is the prose->symbol bridge, not
fusion.

Thresholds are frozen before the first run; the merge formula is not tuned per
query.
