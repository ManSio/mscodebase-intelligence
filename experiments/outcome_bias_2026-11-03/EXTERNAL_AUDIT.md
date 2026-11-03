# External check — Sara Bezjak, `interpretability-grounds-testing`

**Date:** 2026-11-03. **Source:** https://github.com/sbezjak/interpretability-grounds-testing
(report: `sbezjak.github.io/interpretability-grounds-testing/reports/dana-outcome-leak-gemma-2-2b-it-audit.html`).
**Rule:** this file holds our conclusion + short quotes + sha256; the full third-party logs were
downloaded to `%LOCALAPPDATA%/Temp/opencode/sbezjak/` and are not committed (§20.1).

## Verification ledger — report vs its own raw logs

| # | Report claim | Log (sha256 prefix) | Line | Status |
|---|---|---|---|---|
| F1 | no-harm 3.5629, harm 6.2839, leak +2.7211 | `dana-outcome-patching…log` `ebb452b8` | 26-28 | ✅ CONFIRMED verbatim |
| F2 | outcome enters at row 15 (0.5751); row 17 0.8796; row 26 1.0000; controls 0/1 | same `ebb452b8` | 81, 83, 92, 94 | ✅ CONFIRMED verbatim |
| F3 | at rows 16-18 all three hold; row 17 Dana +0.8240 (0.697), Riley +3.1725 (0.923), random +0.031 | `dana-outcome-removal-alltokens…log` `7f746499` | 98-100 | ✅ CONFIRMED verbatim |
| F4 | Dana P 0.91 → 0.55; Jesse 0.825 → 0.5; 95% intervals logged | `moral-luck-06-sep…plain-vs-fixed.log` `e4538e63`; `…intervals.log` `c10eb548` | 2771, 2774; 7, 16 | ✅ CONFIRMED; note intervals overlap at the edge (Dana plain 0.775-0.990, fixed 0.305-0.790) → "supported", not a clean effect |
| F5 | Jesse 9.2% left; Kai 63.4% left and flipped; Dana 30.3% left, liability kept 0.783; Quinn dropped | `outcome-removed-new-cases…log` `789f54e5` | 45-48, 62-64 | ✅ CONFIRMED verbatim |
| F6 | dictionary rebuild: Dana +1.1206 vs +2.7211, off by 0.588; Riley off by 0.635 | `dana-outcome-direction-gemma-scope…log` `c4b3a50e` | 54-55 | ✅ CONFIRMED (gate failed, as reported) |
| F7 | P(EVALUATION) ≈ 0.998; test-minus-real cue ≈ 0.001 | `eval-awareness-dana-cues-smoke…log` `d1a026b2` | 62, 76 | ✅ CONFIRMED (inconclusive, as reported) |
| F8 | removing Riley's direction: Dana leak kept 0.665, Riley gap shrunk 0.925 | `dana-other-direction…log` `53cfdf3a` | 67, 78 | ✅ CONFIRMED; report's "partly shared" is honest |

**Pre-registration:** report says rules were committed after the runs. Verified:
`removal-sturdy` at `2026-10-23T11:34:34Z`, `removed-cases` at `2026-10-23T11:55:38Z`,
commit `42a832add81d2e2bd2906f2b479f6b377b9e9e4f` at `2026-10-23T12:03:26Z` (8 min 48 s after
the last run). So the runs were scored by the rules, not necessarily generated from them. The
report states this itself; the claim is accurate.

**Fixtures:** `moral-luck-02.json` sha256 `7416bb30…`, `moral-luck-06-sep.json` `36820337…` —
both match the report's prefixes.
**Scorer:** `scorer.py` sha256 `d2953a6c…` — matches the report's prefix.
**Tests:** `test_outcome_leak.py` contains **27** test functions (denominator matches). Not
executed here: the repo requires `torch==2.12.1`, which is not installed in our venv. So
"27/27 pass" is ⏳ **not independently reproduced**, only the function count is verified.

## What this changes in our reading

1. The report's numbers are backed by its logs **verbatim** — this is not a "report says more
   than the data" case on the quoted numbers.
2. The report is already honest about its weak spots: F6 (dictionary gate failed), F7 (eval
   awareness inconclusive), F8 (the control's own direction also cuts the leak by ~a third),
   n=10 intervals that overlap, and rules committed after the runs.
3. The one place where the prose could still overreach is the word "confirmed" on F1-F3:
   those are single-model, single-story (Dana picked layer 17) results. The report says this
   in Limits; the Findings table's "confirmed" is stronger than the design supports.

## Cross-reference to our E3/E4

Our local `qwen2.5-3b-instruct` dissociation (action visible without harm: 2 vs 8; invisible
with harm: 8 vs 8) appeared on the driver story. **On 4 held-out stories it did not replicate**
(E6: severe-minus-mild without harm was +3.98, +0.48, -0.86, -2.48; H1 failed 1/4). What
replicates is outcome dominance (outcome gap > action gap, 4/4). So the F8 entanglement idea
is weaker than it looked: the model may simply not have a consistent action-severity axis,
rather than "harm switches it off". That is still a hypothesis, now with a negative held-out
result attached.
