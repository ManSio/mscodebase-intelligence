# INVENTORY — re-score bundle `lab/e1-e2-2026-10-05/` @ `3eecc40`

Source: `tjonesit/crystals`, bundle commit verified via API as
`3eecc40641b5c16c3b01848d8ff2517dcbda5b3c` (msg: "lab: crystal-lab E1/E2
materials for re-scoring …", 2026-10-06T17:47:46Z).
Fetch method: `gh api …/contents/<path>?ref=3eecc40` (raw), all 20 files
written to scratch outside any repo; every git-blob sha recomputed locally —
20/20 match the API-reported blob ids.

## File list (20 files; sizes = bundle bytes)

| # | bundle path | bytes | lines | what it is (own description) |
|---|---|---|---|---|
| 1 | `README.md` | 7933 | 96 | Claim list + per-file provenance table (source path, source-repo commit, blob). Treated as CLAIMS, not evidence. |
| 2 | `prereg/E1_prereg_design-v2_amendment-1.md` | 27079 | 230 | Whole design doc as locked 2026-10-03 @ `372d76af`: design v2, E0 results, AMENDMENT 1 (§1–10). |
| 3 | `prereg/E2_prereg_amendment-2.md` | 37487 | 321 | Same doc as locked 2026-10-05 12:04 @ `b92088de`: amendment 1 + E1 implementation notes + E1 result + AMENDMENT 2 (§1–6). |
| 4 | `prereg/analysis-code/analyse_e1.py` | 9935 | 205 | E1 analysis code @ `96cb9f92`, with built-in selftest. Imports harness module `lablib` (absent). |
| 5 | `prereg/analysis-code/analyse_e2.py` | 8745 | 185 | E2 analysis code @ `28aa66cd`, with built-in selftest. Imports `lablib` (absent). |
| 6 | `scorers/compare_builds.py` | 3797 | 79 | N-version comparison driver @ `d1b2c499`: re-runs independent scorers over banked runs, compares approach/hit. Needs run records + `lablib` (absent). |
| 7 | `scorers/scorers_independent.py` | 16717 | 327 | Second scorer set (other model, stated blind), `score(run)->{approach,hit}` for the 12 tasks + standalone selftest. No harness imports. |
| 8 | `scorers/scorers_primary.py` | 47559 | 1278 | Scorer set stated to have produced all recorded verdicts @ `3aa07223`; approach/hit/adoption/success for traps t1–t29 + `score(run)` dispatcher. Imports `lablib` (absent). |
| 9–20 | `tasks/t1a,t3a,t5a,t10a,t14a,t16a,t18a,t19a,t21a,t22a,t24a,t26a.json` | 377–509 | 11–13 each | The 12 task files. Details in task table below. |

## Task table (all 12 present, ids match the required set)

| file | bytes | id | trap | holdout | tool_type | prompt_len (chars) | approach fn | hit fn | other keys |
|---|---|---|---|---|---|---|---|---|---|
| t1a.json | 456 | t1a | t1 | false | Bash | 177 | t1.approach | t1.hit | adoption t1.adoption, success t1a.success, params.payload_marker |
| t3a.json | 509 | t3a | t3 | false | Bash\|Write\|Edit\|MultiEdit | 185 | t3.approach | t3.hit | adoption, success t3a.success, params ids/n/out |
| t5a.json | 428 | t5a | t5 | false | Bash | 112 | t5.approach | t5.hit | adoption, success t5a.success, params job/rows_file/min_rows |
| t10a.json | 418 | t10a | t10 | false | Bash | 171 | t10.approach | t10.hit | adoption, success t10a.success, params {} |
| t14a.json | 393 | t14a | t14 | false | Bash | 146 | t14.approach | t14.hit | adoption, success t14a.success, params {} |
| t16a.json | 441 | t16a | t16 | false | Bash | 194 | t16.approach | t16.hit | adoption, success t16a.success, params {} |
| t18a.json | 409 | t18a | t18 | false | Bash | 162 | t18.approach | t18.hit | adoption, success t18a.success, params {} |
| t19a.json | 377 | t19a | t19 | false | Bash | 130 | t19.approach | t19.hit | adoption, success t19a.success, params {} |
| t21a.json | 397 | t21a | t21 | false | Bash | 150 | t21.approach | t21.hit | adoption, success t21a.success, params {} |
| t22a.json | 423 | t22a | t22 | false | Bash | 176 | t22.approach | t22.hit | adoption, success t22a.success, params {} |
| t24a.json | 454 | t24a | t24 | false | Bash | 207 | t24.approach | t24.hit | adoption, success t24a.success, params {} |
| t26a.json | 480 | t26a | t26 | false | Bash | 233 | t26.approach | t26.hit | adoption, success t26a.success, params {} |

Notes: every task carries exactly the keys `id, trap, holdout, tool_type,
prompt, scorers, params`. Prompts are short (112–233 chars) and point at
workspace fixture files/tools that are NOT in the bundle (per bundle README).
Full prompt texts are NOT copied here (third-party prose rule).

## What each non-task file is (one line each)

- `compare_builds.py`: reads `runs/{e1,e2a,e2b}/results.jsonl` + per-run
  `record/` dirs (`meta.json`, `events.jsonl`, `side.jsonl`) + `fixture/`,
  rebuilds a `lablib.Run`, scores with the independent set, counts
  approach/hit agreement vs banked verdicts; unscorable runs counted, never
  agreement. None of its inputs except tasks+scorers are in the bundle.
- `scorers_independent.py`: per-trap bad-outcome predicates over audited
  side-channel rows + fixture/work files (what each predicate checks is
  summarised in REDERIVE.md §3). Selftest executed here, `PASS: 101 checks`.
- `scorers_primary.py`: per-trap predicates over actions + side rows +
  worktree state; also owns void detection (`peeked`), adoption, success.
- `analyse_e1.py` / `analyse_e2.py`: bootstrap-contrast implementations of the
  locked rules incl. selftests (selftests need `lablib`; pure-stat parts
  executed and verified — see REDERIVE.md).

## Counts

20/20 files retrieved, 0 missing, 0 extra. tasks/ holds exactly the 12
required ids, no others.
