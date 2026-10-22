# Publication audit — every number we published about crystal-memory / symptom-index / fail-closed

**Date:** 2026-10-06. **Trigger:** T-11 / §19.11 (audit own published numbers before publishing further,
and after any gap > 14 days). **Not pre-registered.** The audit was run *after* the claims were read, so
`MANIFEST_retroactive.md` is a reconstruction of the claim list from the registries, **not** a pre-look
freeze. Stated here so nobody later mistakes it for one.

**Population:** the claims listed in `MANIFEST_retroactive.md`, as they appear in `EXPERIMENTS_LOG.md`,
`AGENT_DIARY.md` and two public venues (dev.to comment threads on article 4680630, GitHub issue
tjonesit/crystals#1).

**Method:** every verdict below comes from re-parsing a raw artifact with a stated rule. A log entry,
a diary line or a published comment was treated as a *pointer only* (§19.2). Where no raw artifact
exists, the verdict is NOT RE-DERIVABLE — never "probably fine".

## Ledger

| # | Claim | Published at | Raw artifact | Verdict |
|---|---|---|---|---|
| 1 | arrival layer maps the dispositional symptom to family A in 5/5 runs; 2 valid; controls 6/6 | dev.to 3fej5, EXPERIMENTS_LOG Exp 23 | **recovered** `frozen/e11_HANDOUT.recovered.md` (sha256 `cd917be4…`) + run stdout recovered from `opencode.db` | ✅ **CONFIRMED** |
| 2 | pinned regression: valid 10/11, `#16 → NONE` in all | GitHub issue #1 | `results/pinned_variant/` (11 files + manifest) | ✅ CONFIRMED |
| 3 | held-out F4b: arrival 10/11 vs symptom 3/11, all symptom failures on one item | AGENT_DIARY, `results/f4b/RESULTS.md` | `results/f4b/**` (22 files) | ⚠️ **PARTIAL** — direction holds, denominator inflated (see §Data defects) |
| 4 | regression on the recovered list: valid 5/11 | `results/recovered_e7/RESULTS.md` | 11 files; `run_longcat_1.txt` genuinely corrupt (file begins with U+FFFD) | ✅ CONFIRMED as recorded |
| 5 | reader stability "one model 8/10, another flipped 6/10" | dev.to 3feh2, EXPERIMENTS_LOG Exp 19 | **none anywhere** | ❌ **WITHDRAWN** |
| 6 | "glm FA 0.24–0.38 vs qwen recall 0.08 → 0.88" | GitHub issue #1 | **none** (data dir empty, never tracked) | ❌ **WITHDRAWN** — category error + no raw |
| 7 | "recall 0.08 → 0.88 (×11)" | GitHub issue #1 | none; 2/25 and 22/25 arithmetic OK | ⚠️ **QUALIFIED** — change of evidence format, not before/after |
| 8 | deterministic 1-V proxy ladder 1.0 / 0.12 / 0.16 / 0.24 | EXPERIMENTS_LOG | `experiments/1V_memory_contamination/memory_contamination_results_v{3_verify,4_rep}.json` | ✅ CONFIRMED — re-derived from JSON |
| 9 | F4 regression: `#16 → NONE` everywhere | EXPERIMENTS_LOG Exp 19 (10/10) | F4 (later, same list) gives 11/11 | ⚠️ supported only by the later replay, not by the original run |

## Withdrawn claims, in detail

**#5 — reader stability.** The denominator does not exist. The surviving runs have 16 items and at
most 5 runs per model. Two defensible rules computed on them disagree about which reader was steadier
(items where a model agreed with itself across all its runs: qwen 11/16, longcat 10/16, deepseek 12/16;
per-item modal agreement: longcat 0.588 ahead of qwen 0.479). Neither rule yields 8/10 vs 4/10, and
the direction is not supported. The original run's per-item verdicts were never committed: the claim
entered git in two Markdown-only commits (`8dc75932`, `03516b24`) and is absent from every other
branch, the stash, the reflog, 2,435 Zed checkpoint trees, 4,650 unreachable blobs and the disk.

**#6 — fail-closed headline.** `0.24` is glm-4.7-flash under the V2-en prompt; `0.38` is
nemotron-nano-30b. We merged two models into one range and wrote it as a single finding; the repo's
own later line (`EXPERIMENTS_LOG.md:481`) states it correctly as two separate values. The per-item
verdicts lived in `<DATA_DIR>/projects/bfe9644b/experiments/`, which is now empty and was never
git-tracked. Only the per-model false-accept item **ids** survive, in
`experiments/1L_live_arm/report.md` §6.2. The 833 KB `openrouter_activity_2026-08-15.csv` is per-call
billing telemetry (4,087 generations): it supports n, cost and truncation, and carries no verdict.

**#7 — the 0.08 → 0.88 framing.** Numerically 2/25 → 22/25 on the same denominator of 25, but the
arms differ: `code_first` vs `file_content_first`. The log's own caveat at that line ("FA not 0.00 but
0.02–0.04") is the first thing dropped when the pair is quoted. Not quotable as an improvement.

## Data defects found in our own artifacts

1. **Inflated denominator (F4b).** `results/f4b/symptom/longcat-2.0/run_longcat-2.0_2.txt` and
   `run_longcat-2.0_5.txt` are byte-identical (sha256 `229e5479…`), while `manifest.json` declares
   `runs_per_model.longcat-2.0 = 5` and `total_runs = 22`. Distinct runs: **21**. So "arrival 10/11 vs
   symptom 3/11" has 11 in the denominator and 10 unique runs behind it. Every symptom failure is on
   the same item, so the direction is untouched; the count is stated with its true denominator from now on.
   Mechanical guard: `scripts/check_duplicate_runs.py` (exit 1 on duplicate/mismatch, **exit 2 on an
   empty population**, `--selftest` 5/5, 16 unit tests).
2. **Encoding corruption masquerading as a data defect.** `results/recovered_e7/run_longcat_1.txt` is
   corrupt at byte level (begins with U+FFFD). An audit pass first reported it as "UTF-16LE, decodes to
   a complete 16-item table, therefore 6/11 valid"; a direct byte check refuted that. The recorded 5/11
   is correct. **The "correction" was never published.**
3. **A results directory whose name is another experiment's.** `results/recovered_e7/` is the 2026-09-26
   regression on the recovered list, **not** Exp 19 (2026-09-22). Its `RESULTS.md` even self-disclaims
   numeric reproduction. Reading it as E7 is a silent experiment substitution.
4. **Ambiguous experiment id.** "E11" denotes two different experiments: Exp 23 (arrival index,
   `EXPERIMENTS_LOG.md` Exp 23) and the search-quality graph-hybrid arm (`EXPERIMENTS_LOG.md` Exp 11).
5. **Stale header.** `experiments/4A_unit_of_return/README.md` opens with "pre-registered, no runs yet"
   while `results/` holds 795 files.

## E11 recovery provenance (why this recovery is legitimate)

| Field | Value |
|---|---|
| Source | `opencode.db` part `prt_0cb1b0cc7001CdV8kjbTE2r8Ii` (tool=`write`, JSON `$.state.input.content`) |
| Original path | `%TEMP%/opencode/e11/handout.md` (directory no longer exists) |
| Session | `ses_f352beffaffe5EFOuUr9vpADUn` |
| Handout written | 2026-09-22T21:52:22.727Z |
| First model call | 2026-09-22T21:52:57Z (**+35 s**) |
| sha256 (expected, pre-registered) | `cd917be4257b65b5ebf511369d5e852d68ff165e7869e7da437f35400170e535` |
| sha256 (materialised) | identical — byte-exact |
| Frozen copy | `experiments/4A_unit_of_return/frozen/e11_HANDOUT.recovered.md` |

The handout is the *input* and was written before any run existed, so the recovery is pre-look and
usable for replay. The run outputs recovered alongside it are *results*; they are kept as evidence of
what happened, not as an input to anything.

Re-derived from the recovered stdout (`# -> entry` format, must-hit {1,4,9}, must-NONE {3,6,11}):

| run | model | must-hit | must-NONE | symptom #16 |
|---|---|---|---|---|
| 1 | deepseek-v4.1-flash | 3/3 | 2/3 (`#11 → generated-document`) | family A |
| 2 | deepseek-v4.1-flash | 3/3 | 2/3 (`#11 → generated-document`) | family A |
| 3a | longcat-2.0 | 3/3 | 3/3 | family A |
| 3b | qwen3.7-plus | 3/3 | 3/3 | family A |

→ 5/5 map to family A; 2 valid runs with controls 6/6; the single failure mode is the declared
false positive on the generated-document entry, which the catalogue publishes as `arrival_fp`.

## What is publishable today

Only rows 1, 2, 8, and row 3 restated with its true denominator. Everything else is either withdrawn or
needs a re-run. Public corrections were posted to tjonesit/crystals#1 (2026-10-06); the originals were
not deleted.
