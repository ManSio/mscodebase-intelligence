# Frozen hypotheses — E-OUTCOME-3 (local small model)

Frozen BEFORE the first E3 call. Same stories and controls as E1/E2.
Purpose: replicate on a small local instruct model (the article's setting), not a hosted API.

| # | Hypothesis | Falsifier | Expected |
|---|---|---|---|
| H1 | Outcome leak > 1.0 on a 0-9 scale | leak <= 1.0 | PASS expected |
| H2 | Leak is uniform across all 4 stories | any story with |leak| < 0.5 or reversed sign | **FAIL expected** |
| H3 | temperature=0 gives identical answers across 5 trials | any cell with >1 distinct value | **FAIL expected** |
| H4 | Positive control: severe action > mild action, gap > 1.0 | pos_gap <= 1.0 | PASS expected; **hard gate** |
| H5 | Negative control (street name) moves blame < 0.5 | neg_delta >= 0.5 | PASS expected |

## Pre-registered rules
- Instrument-valid only if H4 passes.
- If H4 fails, no leak magnitude is published.
- Examples, not a rate; n=4 stories, 1 model, 5 trials.

## Harness note (verified by probe, not assumed)
`qwen2.5-3b-instruct` was the only locally available non-reasoning instruct model that
loaded under LM Studio's resource guardrails (llama-3.2-3b and ministral-3-3b refused to
load: 8.9 GB / 12.6 GB required). `qwen3.5-4b` returns only `reasoning_content` and did
not produce an answer within 400 tokens / 194 s. Therefore E3 is one model, not three.
