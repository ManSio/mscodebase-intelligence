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
| F5 | ~~latency of B is within +0.05 s of A~~ | **retired before the run** (Amendment 1) | — |

Kill: F1 or F4 fails -> keep A. If F2 fails (gain <= 1 task), the weights are
not the binding constraint and the next lever is the prose->symbol bridge, not
fusion.

Thresholds are frozen before the first run; the merge formula is not tuned per
query.

## Amendment 1 — latency is not a criterion (owner decision, 2026-11-10)

Recorded **before the first run**, so the freeze stays honest.

The owner's rule: an agent task runs while the human does something else, and
5-10 s is not a delay. Accuracy and quality decide; latency is a note, never a
pass/fail. Consequences:

- F5 is retired. Latency is still measured and printed for every arm, so a
  regression would be visible, but no arm can win or lose on it.
- Arms may use more expensive computation if it improves accuracy. A formula
  that costs +2 s and gains one task is a win, not a tie.
- The earlier speed comparison against XERJ (8-12 ms vs ~2.6 s per query) is
  not a defect to close. It stays in the reports as context.

The ranking question itself is unchanged: does the channel weight dominate the
per-channel rank enough that ordering inside a channel stops mattering?
