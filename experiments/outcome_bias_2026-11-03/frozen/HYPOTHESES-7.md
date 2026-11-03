# Frozen hypotheses — E-OUTCOME-7 (2x2, unambiguous severity, negative control)

Frozen BEFORE the first E7 call. Local exact readout (logprobs, 0-9).
Four held-out stories where mild and severe are the SAME action type at different
dose (seconds/minute), so severity ordering is not confounded with a different
kind of act. A cosmetic negative control is included in this run (E6 lacked one).

| # | Hypothesis | Falsifier | Expected |
|---|---|---|---|
| H1 | Action readable without harm: severe - mild > 0.5 on >= 3 of 4 | fewer than 3 | PASS expected |
| H2 | Outcome dominates action: outcome_gap(mild) > action_gap(no harm) on >= 3 of 4 | fewer than 3 | PASS expected |
| H3 | Digit mass >= 0.9 in every cell | any cell < 0.9 | PASS expected |
| H4 | Negative control (street name) moves blame < 0.1 | any delta >= 0.1 | PASS expected |
| H5 | Action gap is constant across outcome conditions | any collapse > 0.2 (only where baseline gap > 0.5) | **FAIL expected** |

## Rules
- Instrument-valid only if H3 and H4 pass.
- Collapse is reported only when the no-harm action gap is > 0.5; otherwise "n/a".
- Examples, not a rate. One model, 4 stories + 2 control cells.
