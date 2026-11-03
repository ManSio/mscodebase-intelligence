# PENDING_LEDGER вЂ” proposal for EXPERIMENTS_LOG.md

> This working tree contains untracked experiment dirs from another session, so this
> session does not edit the shared registry (В§21.3). Proposal only.

## Proposed entry

## [2026-11-03] E-OUTCOME-1/2 вЂ” outcome bias in model blame judgments (вЏі instrument failed)

**Design (frozen before run):** 4 paired stories (driver/warehouse/nurse/engineer), same
action, outcome harm vs no-harm; blame 0-9 (E1) and 0-100 (E2); 3 OpenRouter flash models;
5 trials/cell; positive control (action severity, same outcome), negative control
(street name only). Files: `experiments/outcome_bias_2026-11-03/`.

**Raw:** 360 calls, 0 errors. Leak direction positive on 24/24 paired cells.

**Numbers:** E1 positive control FAIL 2/3 (qwen 0.8, deepseek 0.2, glm 4.2); E2 FAIL 3/3
(deepseek 9.0 vs threshold 10, qwen -4.0 with one "10" outlier, glm ignored the 0-100
scale in 12/12 cells). DeepSeek E2 raw leak 56.8-70.4 points. temperature=0/seed=42:
1-6 of 12 cells per model varied across 5 trials.

**Verdict:** вЏі not a measurement. Raw effect is large and direction-consistent, but the
pre-registered positive control failed, so no leak magnitude is published. This is a
live instance of "the number moved, the control did not pass".

**Lesson:** a numeric blame scale saturates exactly where the effect is large. Next
design: pairwise forced choice, no ceiling; keep positive control as a hard gate.

**Links:** `experiments/outcome_bias_2026-11-03/RESULTS.md`.

## Addendum — E3/E4 local

Local qwen2.5-3b-instruct (LM Studio): E3 leak 6-7 pts on 4/4 stories, deterministic, pos control flat (8 vs 8). E4 dissociation: with no harm, severe vs mild = 8 vs 2 (gap 6); with harm, 8 vs 8 (gap 0); neg control 0. Verdict: outcome dominance is real on the local model; hosted positive control earlier failed for instrument reasons.


## Addendum 2 — E5 exact readout + tooling

Local qwen2.5-3b-instruct, expected blame from logprobs (mass ~1.0): leak 5.36 / 5.91 / 6.66 / 6.01 on 4/4 stories; pos control 7.50 vs 8.94; neg 0.067. Hosted GLM binary YES/NO: 3/4 stories 0->1, but positive control flat (1.00 vs 1.00) -> not instrument-valid; engineer story (outage) never owes compensation -> binary question is harm-type-specific. Tooling added: prompts.py (scale consistency), readout.py (exact readout), tests (16 pass, controls can fail), scripts/freeze_manifest.py (selftest passed, raw-after-freeze check passed).

## Addendum 3 — E6 held-out 2x2 (negative result)

Local qwen2.5-3b-instruct, exact readout, 4 held-out stories (cyclist/cook/lifeguard/electrician), 16 cells, mass >= 0.945.
Action gap without harm (severe-mild): +3.98, +0.48, -0.86, -2.48 -> H1 FAIL (1/4). Outcome gap > action gap: 4/4 (H3 PASS). E4 dissociation was story-specific. Robust finding = outcome dominance, not action readability.
Process: run_e6.py edited after freeze (--retry for one transient LM Studio 400); freeze_manifest check correctly FAILs on that file. Recorded, not silently re-frozen.
