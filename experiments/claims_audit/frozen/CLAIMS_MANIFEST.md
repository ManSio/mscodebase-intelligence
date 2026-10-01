# CLAIMS MANIFEST v1 — audit of our own public numbers (mirror of Tom's 84→107 correction)

**Frozen:** 2026-09-30, BEFORE reading any raw result data for this audit.
**Rule (freeze-before-look):** this list is not edited after seeing results. A claim that turns out
to be untestable is marked `CANNOT VERIFY` — it is NOT dropped and NOT reworded to a weaker version
after the fact. Additions require a new v2 with a new sha256.
**Question per claim:** would this number survive being recomputed today, from the artifact that
produced it, on this machine, at this commit?

**Commit at freeze:** `ea9b5911`

## Tier A — deterministic re-run (script exists, no LLM, no network)

| # | Claim (as published) | Source | Rerun target |
|---|---|---|---|
| A1 | E7/F4 pinned: valid **10/11**, controls **6/6**, `#16→NONE` in 10/10 | `results/pinned_variant/RESULTS.md` | re-aggregate `run_*.txt` + valid-run census |
| A2 | F4b arrival: clean **10/11** (must-hit 33/33, must-NONE 32/33) | `results/f4b/RESULTS.md` | `scripts/f4b_aggregate.py` on stored json |
| A3 | F4b symptom: clean **3/11** (`#3` false positive) | same | same |
| A4 | F5 judged: A **16.3%** / B **34.4%** / C **97.5%** / D **0.0%**; code B **50%** vs A **6.3%**; prose A **26%** vs B **19%** | `results/f5judged/judged_aggregate.json` | recompute from `judged_raw.json` |
| A5 | F5 relang: RU **26/80 = 32.5%** vs EN **30/80 = 37.5%** (CI includes 0 → not significant) | `results/f5relang/aggregate.json` | recompute from `en|ru/judged_raw.json` |
| A6 | E11: arrival `#16→NONE` **5/5**, controls **6/6** | diary E11 | re-aggregate `results/f4b/arrival/*` |
| A7 | NodeRAG: TF-IDF top-10 **80%** hit vs graph BFS **70%** | `experiments/noderag/results.json` | `run_experiment.py` |
| A8 | canary shadow: **5/5** attacks passed pre-fix, **0** after, **13/13** tests | `experiments/canary_shadow/exp_canary_attack.py` | rerun + `pytest tests/test_shadow_canary.py` |
| A9 | evalmut: mutation score **8% → 100%** (11/11 polarity holes) | `experiments/evalmut/probe_evalmut_transfer.py` | rerun |
| A10 | lock zombie: orphan wait **30s → 120ms**, healthy **1.5s** soft, **+17** tests | `experiments/lock_zombie/benchmark_selfhealing.py` | rerun + `pytest tests/test_database_lock_selfhealing.py` |
| A11 | vacuous scan: **1133** proven / **3** vacuous / **7** skip of 1143 | `experiments/misc_probes/exp_vacuous_scan.py` | rerun |
| A12 | ln.strip class: broken extractor **3/8** false passes, correct **0/8** | `exp_ln_strip_repro.py` | rerun |
| A13 | population blindspot: EMPTY and GARBAGE emit the SAME signal; control real = 3 | `exp_population_blindspot.py` | rerun |
| A14 | verify_clean_state drift-gate **structurally unable to fire** (TOML-array grep); vacuous suite → PASSED | `exp_verify_gate.sh` | rerun both parts |

## Tier B — LLM-dependent, cannot re-run (cost/network) → re-aggregation only

| # | Claim | Why not re-runnable | Fallback |
|---|---|---|---|
| B1 | E7 live: qwen **8/10** vs longcat **4/10** on same index | requires live model calls | stored raw + arithmetic only |
| B2 | FA rates glm **0.24–0.38** / qwen recall **0.08→0.88** (V4 arm) | live calls, 2026-08 | arithmetic on stored aggregates; label correction already recorded |
| B3 | F5 head-to-head reranker vs word-overlap: 5.7 / 16.0 points, bar 10, inconclusive | this is Tom's arm, not ours | out of scope (not our claim) |

## Declared weaknesses (recorded BEFORE re-running, so they cannot be discovered post-hoc)

- **W1 (A1/A2/A3/A6):** re-aggregation proves the *arithmetic* over stored outputs, not that the
  original run happened as reported. Stated as `arithmetic CONFIRMED`, never as `experiment CONFIRMED`.
- **W2 (A10):** 120ms / 1.5s are wall-clock on the author's machine; drift is expected. Verdict is
  `directional` unless the same order of magnitude holds.
- **W3 (A7/A8/A9):** reruns touch the live index/DB/LLM-free code paths; if the environment has drifted
  since 2026-08, a mismatch is evidence about the environment, not automatically a false claim. Both
  are recorded.
- **W4 (A11):** test count has grown since 2026-08-11, so 1143 is expected NOT to reproduce. A mismatch
  here is predicted and is not a refutation of the 2026-08 measurement.
- **W5:** B1/B2 are not independently verifiable in this session at all. Verdict is `CANNOT VERIFY`,
  not `CONFIRMED`.
