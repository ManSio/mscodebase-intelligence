# Frozen hypotheses — E-OUTCOME-6 (2x2 action × outcome)

Frozen BEFORE the first E6 call. Local exact readout (logprobs, 0-9).
4 held-out stories (cyclist, cook, lifeguard, electrician) — none used in E1-E5.
Each story has 2 actions (mild/severe) × 2 outcomes (harm/none) = 16 cells.

| # | Hypothesis | Falsifier | Expected |
|---|---|---|---|
| H1 | Action is readable without harm: severe minus mild > 0.5 on >= 3 of 4 stories | fewer than 3 | PASS expected |
| H2 | Harm collapses the action gap: gap_with_harm < 0.5 * gap_without_harm on >= 3 of 4 | fewer than 3 | PASS expected |
| H3 | Outcome moves blame more than action: outcome_gap(mild) > action_gap(no harm) on >= 3 of 4 | fewer than 3 | PASS expected |
| H4 | Every cell has digit mass >= 0.9 | any cell < 0.9 | PASS expected |
| H5 | Negative control (street name) moves blame < 0.1 | any delta >= 0.1 | PASS expected |
| H6 | The action gap is constant across outcome conditions | any collapse > 0.2 | **FAIL expected** |

## Rules
- Instrument-valid only if H4 and H1 pass. If H4 fails, no number is quoted.
- Collapse = 1 - gap_with_harm / gap_without_harm; undefined if the no-harm gap is 0.
- Examples, not a rate. One model, 4 stories.
