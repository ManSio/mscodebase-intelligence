# Frozen hypotheses — E-OUTCOME-5 (exact readout)

Frozen BEFORE the first E5 call. Local: expected blame from token logprobs (exact).
Hosted: binary liability YES/NO (OpenRouter does not return logprobs for this model).

| # | Hypothesis | Falsifier | Expected |
|---|---|---|---|
| H1 | Local exact leak > 0.5 blame points on all 4 stories | any story <= 0.5 | PASS expected |
| H2 | Local digit mass >= 0.9 in every cell | any cell < 0.9 | PASS expected |
| H3 | Hosted YES-rate after harm exceeds no-harm by >= 0.2 on >= 3 of 4 stories | fewer than 3 | PASS expected |
| H4 | Positive control separates actions (local blame gap > 0.5; hosted rate gap > 0.2) | gap below threshold | PASS is the gate |
| H5 | Negative control (street name) moves blame by < 0.1 | any delta >= 0.1 | PASS expected |
| H6 | Exact readout makes the effect uniform across stories | any story |leak| < 0.5 | **FAIL expected** |

## Rules
- Instrument-valid only if H2 and H4 pass.
- If H4 fails, no leak number is quoted (same rule as E1-E4).
- One model per arm, 4 stories, 5 trials for the binary arm. Examples, not a rate.
