# E-OUTCOME-1 / E-OUTCOME-2 — results (outcome bias in model blame judgments)

**Date:** 2026-11-03. **Provider:** OpenRouter. **Cost:** ~$0.01 total.
**Calls:** 360 (180 per experiment), 0 HTTP errors, 0 unparsed answers.
**Frozen design:** `frozen/HYPOTHESES.md`, `frozen/HYPOTHESES-2.md`, `frozen/MANIFEST.md`, `frozen/MANIFEST-2.md`.
**Raw:** `results/raw_e1.jsonl`, `results/raw_e2.jsonl`. **Analysis:** `analyze.py`.

## What was measured

Four story pairs. In each pair the **action is identical**; only the last sentence
changes (harm vs no harm). The model is asked to score blame for the *choice* 0-9 (E1)
or 0-100 (E2). Positive control: same outcome (harm), different action severity.
Negative control: same action+outcome, only the street name changes.

## E1 — 0-9 readout

| Model | leak driver | leak warehouse | leak nurse | leak engineer | pos_gap (>1.0) | neg_delta (<0.5) | instrument-valid? |
|---|---|---|---|---|---|---|---|
| qwen/qwen3.6-flash | 0.4 | 1.2 | 4.6 | 1.0 | **0.8 FAIL** | 0.0 PASS | ❌ no |
| deepseek/deepseek-v4-flash | 9.0 | 9.0 | 9.0 | 1.0 | **0.2 FAIL** | 0.0 PASS | ❌ no |
| z-ai/glm-4.7-flash | 5.0 | 9.0 | 9.0 | 6.6 | 4.2 PASS | 0.0 PASS | ✅ yes |

- Leak direction positive on **12 of 12** story/model cells.
- Magnitude is **not uniform**: from 0.4 to 9.0 (H2 refuted, as pre-registered).
- **Only GLM passes the positive control.** The other two saturate: both mild and severe
  actions get ~9, so the instrument cannot show it separates actions from outcomes.

## E2 — 0-100 readout (pre-registered attempt to remove the ceiling) — SUPERSEDED by E2FIX

> **Superseded 2026-11-03:** this run used a system prompt hard-coded to "0-9" while the
> user prompt asked for 0-100. E2FIX below repeats it with a scale-aware prompt. E2's
> numbers are kept for history, not quoted as the corrected measurement.

| Model | leak driver | leak warehouse | leak nurse | leak engineer | pos_gap (>10) | neg_delta (<5) | instrument-valid? |
|---|---|---|---|---|---|---|---|
| deepseek/deepseek-v4-flash | 64.0 | 56.8 | 70.4 | 63.0 | **9.0 FAIL** (by 1 pt) | 0.0 PASS | ❌ no (near miss) |
| qwen/qwen3.6-flash | 12.0 | 9.0 | 38.0 | 2.0 | **-4.0 FAIL** (one "10" among 100s) | 0.0 PASS | ❌ no |
| z-ai/glm-4.7-flash | 4.0 | 9.0 | 9.0 | 9.0 | 3.0 FAIL | 0.0 PASS | ❌ no — **answered 0-9 on a 0-100 prompt in 12/12 cells** |

- DeepSeek: no-harm 9.0-16.0, harm 65.8-80.0. The raw gap (57-70 points) is large and
  direction-consistent, but the positive control lands at 9 points against a pre-registered
  threshold of 10. By our own rule this is **not** a measurement.
- Qwen: one answer of "10" in the severe condition pulls the mean down; without that single
  outlier the control would pass. We do not remove it post-hoc.
- GLM: scale-following failure — concrete, reproducible confound.

## E2FIX — corrected hosted 0-100 (supersedes E2)

Same models, same stories, same 0-100 scale; the only change is a scale-aware system prompt.
180 calls, 0 errors. Raw: `results/raw_e2fix.jsonl`.

| Model | leak (4 stories) | pos_gap (>10) | neg_delta | instrument-valid? |
|---|---|---|---|---|
| z-ai/glm-4.7-flash | 72 / 100 / 100 / 100 | **62.0 PASS** | 0.0 | ✅ yes |
| qwen/qwen3.6-flash | 13 / 13 / 41 / 6 | 5.0 FAIL | 0.0 | ❌ no |
| deepseek/deepseek-v4-flash | 0 / 0 / 69 / 20 (driver+warehouse both 100) | 0.0 FAIL | 0.0 | ❌ no (ceiling) |

GLM concrete means: driver 20 -> 92, warehouse 0 -> 100, nurse 0 -> 100, engineer 0 -> 100;
positive control mild 38 vs severe 100; negative control 100 vs 100. This is a hosted
replication with a **passing** positive control and a zero negative control.

## Determinism (H3) — refuted

Same prompt, temperature=0, same seed=42, 5 trials.
- E1: 1-4 of 12 cells per model had more than one distinct value.
- E2: up to 6 of 12 cells per model had more than one distinct value.
Concretely, GLM on `driver/no_harm` (E1) gave 9, 9, 9, 8, 8; DeepSeek on
`driver/no_harm` (E2) gave 0, 20, 20, 20, 20. **temperature=0 is not determinism on this harness.**

## Verdict

**⏳ Not a measurement of outcome bias.** The direction is consistent (24 of 24
paired cells across both runs) and the raw effect is large on DeepSeek. But the
pre-registered positive control — the thing that proves the instrument can
distinguish "action" from "outcome" — failed on 2/3 models in E1 and 3/3 in E2.
What we can say safely:

1. On these three hosted models, the raw blame gap between harm and no-harm is
   always in the expected direction; on DeepSeek at 0-100 it is 57-70 points.
2. The instrument we chose (single integer, 5 trials) is not good enough to certify
   that gap: the scale saturates, one model ignores the scale, and temperature=0
   does not repeat.
3. This is a concrete instance of the article's own lesson: the number moved, the
   control did not pass, and reporting "outcome bias = 60 points" would be wrong.

## Process failures (own, not hidden)

- E2's frozen hashes were **not recorded before the run**. The files were written before
  it (see mtime vs `raw_e2.jsonl`), but freeze-before-look was not mechanically closed.
- The first E1 raw file was named `raw.jsonl` and renamed to `raw_e1.jsonl` after the run.
- `_probe_raw.py` and `_probe_logprobs.py` are disposable probes, not part of the design.

## CORRECTION 2026-11-03 — E2 scale-following was our bug, not the model's

The E2 system prompt was hard-coded to "answer with a single digit from 0 to 9" even when
the user prompt asked for 0-100. So the GLM "ignored the scale in 12/12 cells" finding is
**not** a model defect: our own system prompt told it 0-9. This invalidates the
scale-following interpretation of E2. The raw E2 leak numbers are unaffected (they are
within-model harm vs no-harm comparisons), but the "model ignores scale" claim is withdrawn.

## E3 — local model (qwen2.5-3b-instruct, LM Studio, 0-9)

60 calls, 0 errors, all 5 trials identical in every cell (this local model *is* deterministic
at temperature=0, unlike the hosted ones).

| Story | no-harm | harm | leak |
|---|---|---|---|
| driver | 2.0 | 8.0 | 6.0 |
| warehouse | 2.0 | 9.0 | 7.0 |
| nurse | 2.0 | 9.0 | 7.0 |
| engineer | 2.0 | 9.0 | 7.0 |
| neg control (Elm vs Pine) | 8.0 | 8.0 | 0.0 |

Leak positive on **4 of 4** stories, magnitude 6-7 points. Positive control (mild vs severe,
both harm) was flat again: 8.0 vs 8.0, gap 0.0.

## E4 — action-sensitivity control (same local model)

30 calls, 0 errors, deterministic. Same actions as the positive control, but outcome varied:

| condition | mild action (1 s @15) | severe action (12 s @50) | action gap |
|---|---|---|---|
| **no harm** | 2.0 | 8.0 | **6.0** |
| **with harm** | 8.0 | 8.0 | **0.0** |
| negative control (Elm vs Pine) | 8.0 | 8.0 | 0.0 |

**This resolves the ambiguity.** The model *can* separate action severity — it does so when
nothing bad happens (2 vs 8). When the outcome is harm, both actions hit 8 and the difference
disappears. That is not a broken ruler and not scale saturation: it is **outcome dominance**.
The outcome gap for the mild action is +6 (2 -> 8); for the severe action it is 0 (already at
ceiling).

## Updated verdict

- **Hosted models (E1/E2FIX):** on z-ai/glm-4.7-flash the effect is large (72-100 points on
  0-100, 4/4 stories) and the instrument is certified: positive control 38 vs 100 (gap 62),
  negative control 0. On qwen3.6-flash and deepseek-v4-flash the positive control failed
  (gap 5 and 0), so their raw gaps are not quoted. E2's "model ignores scale" finding was
  our prompt bug and is withdrawn (E2FIX fixes it).
- **Local small model (E3/E4/E6):** outcome dominance replicates — the outcome moves blame
  far more than the action manipulation on 4/4 held-out stories (E6), and E5's exact readout
  gives 5.36-6.66 points on a 0-9 scale with mass ~1.0.
- **But the earlier dissociation did NOT generalize.** E4's "action is visible without harm"
  held on the driver story only. On the 4 held-out stories (E6) severe-minus-mild without
  harm was +3.98 (cyclist), +0.48 (cook), -0.86 (lifeguard), -2.48 (electrician): 1 of 4,
  which fails the pre-registered H1. **E4 is story-specific, not a general mechanism.**
- **Scope:** one 3B model, 4 held-out stories, exact readout. Examples, not a rate. Says
  nothing about frontier models.

## Next

- Run the E4 dissociation on 2-3 more models (hosted and local) to see whether
  "action sensitivity exists without harm" is universal or model-specific.
- Pairwise forced choice remains the better readout for avoiding the ceiling.

## E5 — exact readout (logprobs) + binary hosted fallback

Frozen via `scripts/freeze_manifest.py` before the run (`frozen/MANIFEST-5.json`,
`--raw` check passed for both arms). 72 calls, 0 errors.

**Local `qwen2.5-3b-instruct`, exact expected blame from token logprobs (0-9):**

| story | no harm | harm | leak | digit mass |
|---|---|---|---|---|
| driver | 3.282 | 8.641 | 5.359 | 1.000 |
| warehouse | 3.068 | 8.982 | 5.913 | 1.000 |
| nurse | 2.334 | 8.991 | 6.657 | 1.000 |
| engineer | 2.980 | 8.989 | 6.009 | 1.000 |
| pos control (both harm) | mild 7.501 | severe 8.939 | gap 1.438 | 1.000 |
| neg control | Elm 8.787 | Pine 8.719 | delta 0.067 | 1.000 |

- H1 (leak > 0.5): PASS, 4/4. H2 (mass >= 0.9): PASS. H4 (pos > 0.5): PASS. H5 (neg < 0.1): PASS.
- H6 (uniformity): PASS by the pre-registered falsifier (no story < 0.5); exact readout is
  more uniform than the sampled one (5.36-6.66 vs 6-7), though not identical.

**Hosted `z-ai/glm-4.7-flash`, binary liability YES/NO (logprobs unavailable):**

| story | YES no harm | YES harm | delta |
|---|---|---|---|
| driver | 0.00 | 1.00 | +1.00 |
| warehouse | 0.00 | 1.00 | +1.00 |
| nurse | 0.00 | 1.00 | +1.00 |
| engineer | 0.00 | 0.00 | 0.00 |
| pos control | mild 1.00 | severe 1.00 | 0.00 FAIL |
| neg control | 1.00 | 1.00 | 0.00 |

- Effect on 3/4, **but the positive control fails** (both severities YES 5/5) -> arm is
  **not instrument-valid**, rates are not quoted as a measurement.
- Engineer (production outage) gets NO even with harm: "compensation to the injured person"
  is harm-type-specific. Design flaw in the binary arm, not a model finding.
- H3 passed mechanically (3/4) but H4 failed; by the pre-registered rule, no result.

## E6 — 2x2 action × outcome on 4 held-out stories (local exact readout)

Frozen before the run (`frozen/MANIFEST-6.json`). 16 cells, all parsed after one retry of a
transient LM Studio HTTP 400 (`Engine protocol startup was aborted`). Digit mass min 0.945.

| story | mild no harm | severe no harm | action gap (no harm) | mild harm | severe harm | action gap (harm) | outcome gap (mild) |
|---|---|---|---|---|---|---|---|
| cyclist | 0.022 | 4.001 | **+3.979** | 5.607 | 7.036 | +1.430 | +5.584 |
| cook | 1.436 | 1.917 | +0.481 | 4.282 | 6.854 | +2.572 | +2.846 |
| lifeguard | 4.003 | 3.141 | **-0.861** | 5.169 | 5.723 | +0.554 | +1.166 |
| electrician | 3.092 | 0.617 | **-2.475** | 7.802 | 8.092 | +0.291 | +4.709 |

| # | Hypothesis | Result |
|---|---|---|
| H1 | action readable without harm (>0.5 on >=3/4) | **FAIL — 1/4** |
| H2 | harm collapses the action gap (>0.5 on >=3/4) | **NOT INTERPRETABLE** — 3/4 by ratio, but 2 of those baselines are negative, so the ratio is meaningless; only cyclist has a positive baseline (collapse 0.64) |
| H3 | outcome gap > action gap (no harm) on >=3/4 | **PASS — 4/4** |
| H4 | digit mass >= 0.9 in every cell | PASS (min 0.945) |
| H5 | negative control < 0.1 | **⏳ NOT RUN in E6** (no cosmetic cell in this story set) |
| H6 | action gap constant across outcomes | refuted, as expected |

**Meaning:** the robust finding is **outcome dominance** (4/4). The claim "the model can read
severity, the outcome just flattens it" does **not** survive held-out stories: on 3 of 4 the
model did not rank the severe action above the mild one even with no harm. The E4
dissociation was one story (driver).

**Process violation (own):** `run_e6.py` was edited **after** the freeze to add `--retry`
(recovering one transient HTTP 400). `freeze_manifest.py check` correctly reports
`FAIL changed input: run_e6.py`. The measurement files (`run_exact_readout.py`, `readout.py`,
`prompts.py`), hypotheses and stories match the freeze; the retry used the same
`local_expected`. Strict freeze for the runner file is broken and is recorded, not re-frozen.

## Tooling added (this session)

- `prompts.py` — one source of truth for scale wording + `prompt_scale_mismatch()`.
- `readout.py` — `expected_blame`, `digit_mass`, `mass_gate`, `fraction_restored/removed`,
  `detect_scale_following`, `parse_yes_no`, `digit_probs_from_logprobs`.
- `tests/test_readout.py`, `tests/test_prompt_scale_consistency.py` — 16 tests, both include
  a control that must fail (zero mass -> nan; the known E2 mismatch must be caught).
- `scripts/freeze_manifest.py` — `write` / `check --raw` / `--selftest`; the selftest tampers
  an input and moves a raw file before the freeze, and both are caught (PASSED).

## Process failures (own, not hidden)

- E2 system prompt contradicted the user prompt (0-9 vs 0-100) — found and corrected;
  the affected claim is withdrawn above.
- E2's frozen hashes were not recorded before the run; E3/E4 hashes were recorded before
  their runs (`frozen/MANIFEST-3.md`, `frozen/MANIFEST-4.md`).
- First E1 raw file renamed after the run (`raw.jsonl` -> `raw_e1.jsonl`).
