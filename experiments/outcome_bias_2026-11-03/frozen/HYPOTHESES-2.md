# Frozen hypotheses — E-OUTCOME-2 (finer readout replication)

Frozen BEFORE the first E2 API call. Same 4 paired stories and controls as E1
(no story was edited after E1 results). Only the readout changes: 0-100 integer
instead of 0-9 single digit. Purpose: test whether the E1 saturation is a
property of the model or of the instrument.

| # | Hypothesis | Falsifier | Expected |
|---|---|---|---|
| H1 | At 0-100 the ceiling disappears: no cell is saturated (mean >= 95 or <= 5 for all 5 trials) | any saturated cell on >=2 models | PASS expected |
| H2 | Outcome leak (harm - no_harm) > 5 points on at least 2 models | leak <= 5 on >= 2 models | PASS expected |
| H3 | Positive control separates actions: severe - mild > 10 points on at least 2 models | pos_gap <= 10 on >= 2 models | PASS expected |
| H4 | Leak is uniform across all 4 stories on every model | any story with |leak| < 5 or reversed sign | **FAIL expected** |
| H5 | Negative control (street name) moves blame < 5 points | neg_delta >= 5 | PASS expected |

## Pre-registered decision rules (same as E1)
- A model is instrument-valid only if H3 passes (pos_gap > 10).
- If H5 fails, the model is noisy and its leak is not a result.
- Examples, not a rate. No aggregate model claim.
