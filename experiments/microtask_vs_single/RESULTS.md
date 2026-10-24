# Pilot results — microtask_vs_single (2026-10-20)

**Status:** pilot complete. **No quality claim is made** (see §5).
Raw artifacts: `runs/<run_id>/` (gitignored), summary: `results_summary.json`,
collector: `harness/collect_results.py` (re-derives every number from the run
directories).

## 0. Main run on real bugs (added later the same day)

The pilot above was a smoke test on synthetic tasks (both arms 4/4). The main
run uses the **corpus built from our own history**: 12 real bugs (parent commit
of a fix commit), each with the module's own test file as the hidden test, plus
`no-op` and `legitimate-block` variants (24 tasks, corpus control 24/24 PASS).

Both arms execute on the **same gateway** (`tirtha/auto`, `mode=low`, through
our proxy): arm A = one long session, arm C = planner + bounded Briefs +
one-shot workers. The planner is a different model
(`opencode-go/minimax-m3.1-flash-free` — no Claude/Codex is reachable in this
environment) and is recorded as such.

### By class

| class | arm | runs | passed | tokens total | worst run | max prompt tokens | max requests |
|---|---|---|---|---|---|---|---|
| fix | A | 12 | **1** | 15 193 554 | 5 326 158 | **87 586** | 81 |
| fix | C | 16 | **4** | 2 900 386 | 697 956 | 58 121 | 23 |
| no-op | A | 6 | **6** | 479 231 | 141 473 | 39 962 | 7 |
| no-op | C | 6 | **6** | 206 953 | 92 669 | 28 847 | 5 |
| block | A | 5 | **5** | 140 111 | 37 149 | 12 751 | 6 |
| block | C | 3 | **1** | 431 729 | 413 988 | 24 082 | 23 |

### Per task (fix class, 12 tasks)

| task | A | tokens | C | tokens |
|---|---|---|---|---|
| 001f7d3a41_write_tools | 1/1 | 5 326 158 | 1/1 | 697 956 |
| 41355628_health | 0/2 | 5 963 549 | **3/4** | 265 680 |
| 11c88afca6_bootstrap_entities | 0/1 | 176 633 | 0/1 | 37 225 |
| 01d1cce11d_codebase_tool | 0/1 | 135 077 | 0/1 | 198 553 |
| 32f1166290_index_project_runner | 0/1 | 1 355 870 | — | — |
| 6e63f85ac3_cypher_executor | 0/1 | 364 990 | 0/1 | 506 212 |
| 8a05b599f6_verify_on_read | 0/1 | 431 074 | 0/1 | 146 108 |
| 9b66fbed2a_parser | 0/1 | 613 312 | 0/1 | 696 117 |
| a7c221f88d_parser | 0/1 | 498 361 | 0/1 | 86 741 |
| a189d13d_file_guard | 0/1 | 233 312 | 0/3 | 111 495 |
| 05493c6e_project_resolution | — | — | 0/1 | 58 523 |
| ed0f88004b_context_tool | 0/1 | 95 218 | 0/1 | 95 776 |

### What the main run says

1. **The single-session arm breaks the context budget.** A peaked at **87 586
   prompt tokens** — above our 79 k per-request ceiling — and one run burned
   5.3 M tokens (81 requests) to solve a single bug. C peaked at 58 121 and its
   worst run cost 698 k. Over the same 12 tasks: **A ≈ 15.2 M tokens, C ≈ 2.9 M
   (5.2×)**; per task, C is the cheaper arm in 8 of 12.
2. **Quality: A 1/12 tasks, C 2/12 tasks.** The difference is one task, which
   is **not** a quality claim at this n. The one task only C solved
   (`41355628_health`) is exactly the one where A ran away (0/2, 5.96 M
   tokens) — consistent with the mechanism being step count, not intelligence.
3. **On 10 of 12 real bugs both arms fail.** With a cheap-tier executor
   (`mode=low`, Base-only) the *model* is the bottleneck; no architecture fixes
   a model that cannot do the task. This is the honest headline of the main
   run, and it is the same lesson as Tīrtha's own "a crystal cannot help where
   the model is not going to make the mistake".
4. **Both arms handle "nothing to change" correctly** (no-op: 6/6 and 6/6).
5. **The microtask arm is worse on the block class** (1/3 vs 5/5): its worker
   retries an unrunnable acceptance command (23 requests, 414 k tokens) instead
   of reporting the missing specification. We added a step budget
   (`session/cancel` watchdog) after observing this — the baseline is
   deliberately left unbounded, because its runaway is the measurement.

### The receipt contract (2026-08-21 correction that changed the conclusion)

Measured: **10 of 998** provider responses had *exactly* 1024 completion tokens
(the Base tier's output cap), and 8 of our verdicts coincide with an answer cut
at that cap. We were asking the worker to return a **diff inside its answer** —
so long answers were cut, and every later turn re-sent the diff, which is what
inflated the baseline's context to 87 586 tokens.

The contract is now: the answer carries a **receipt** (status, files, test
command + exit code), the artifact stays on disk, and the harness computes the
diff. Answer length on the same task fell from ~700–1 000 tokens to **90**.

| task | arm | old contract | new contract |
|---|---|---|---|
| 001f7d3a41_write_tools | A | pass, 81 req, **5 326 158** tokens, 296 s | pass, 11 req, **399 532** tokens, 68 s |
| 001f7d3a41_write_tools | C | pass, 16 req, 697 956 tokens | fail, 5 req, **116 956** tokens, 257 s |
| 11c88afca6_bootstrap_entities | A | fail, 13 req, 176 633 | fail, 7 req, 77 268 |
| 11c88afca6_bootstrap_entities | C | fail, 4 req, 37 225 | fail, 12 req, 179 127 |
| a189d13d_file_guard | A | fail, 16 req, 233 312 | **pass**, 27 req, 465 135 |
| a189d13d_file_guard | C | fail, 5 req, 50 274 | fail, 5 req, 47 698 |

Two consequences, both uncomfortable and both real:

1. **A large part of the "microtasks are cheaper" result was our own prompt.**
   The baseline's 5.33 M-token runaway is mostly the diff travelling in the
   answer. With the receipt contract the same task costs 0.40 M (13× less) and
   the same outcome.
2. **The quality signal flips with n.** On the three tasks re-run under the new
   contract, A = 2/3 and C = 0/3 — the opposite of the single contested task
   that motivated the architecture. At n=3 neither is a result. The earlier
   "C wins" reading is therefore **not** supported once the answer-bloat
   confound is removed.

Conclusion kept from the data: the **cost and context bound** is real and
measured; the **quality advantage of microtasks is not demonstrated** and must
not be claimed until a ≥10-task run at a matched token budget is done.



- The first corpus task was **rename-shaped** (the "fix" was an API rename, so
  the expected direction was unknowable from inside the snapshot) → withdrawn;
  the builder now rejects rename-shaped fixes.
- The hidden verdict compared a **raw** sha against a **normalised** one
  (CRLF vs LF) → 8 runs were wrongly marked failed; `harness/reevaluate.py`
  re-derived them from the preserved worktrees (this is why the no-op class is
  6/6, not 0/6).
- A missing file referenced by an acceptance command **crashed** the brief
  builder — which is exactly the block class → the brief now states that the
  file is absent.
- `Path.write_text` without `encoding=` wrote with the Windows locale codec
  (cp1251) and killed 4 runs on an emoji in the agent's answer.
- The plan gate rejected 2-file plans and the arm died; a deterministic
  fallback plan (recorded as `plan_source`) now keeps the arm measuring the
  worker instead of the planner's formatting.
- `Remove-Item -LiteralPath ...\*.json` does not expand wildcards → three
  withdrawn tasks silently stayed in the corpus.


## 1. What was run

| Cell | Command | Outcome |
|---|---|---|
| A/P1 | `python experiments/microtask_vs_single/harness/runner.py --arm A --task P1_mean` | `pass` |
| A/P2 | `python experiments/microtask_vs_single/harness/runner.py --arm A --task P2_money` | `pass` |
| D/P1 | `python experiments/microtask_vs_single/harness/runner.py --arm D --task P1_mean` | `pass` |
| D/P2 | `python experiments/microtask_vs_single/harness/runner.py --arm D --task P2_money` | `pass` |

Arm A = one OpenCode session. Arm D = planner → plan gate → bounded Briefs →
one-shot Tīrtha workers, one file each, sequential.

## 2. Results (from `results_summary.json`)

| task | arm | outcome | wall_s | hidden_rc | changed files | scope violations | agent requests | agent tokens | worker requests | worker prompt max | worker tokens sum |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1_mean | A | pass | 16.0 | 0 | 1 | 0 | 4 | 7 628 | — | — | — |
| P1_mean | D | pass | 101.0 | 0 | 1 | 0 | 2 (planner) + 5 (worker) | planner 6 004 in / 199 out | 5 | 7 094 | 29 172 |
| P2_money | A | pass | 47.0 | 0 | 2 | 0 | 5 | 14 308 | — | — | — |
| P2_money | D | pass | 98.0 | 0 | 2 | 0 | 2 (planner) + 11 (worker) | planner 7 265 in / 431 out | 11 | 7 451 | 66 984 |

Readings:

- **Quality:** 4/4 cells pass. With two easy tasks this is a ceiling effect,
  not evidence that microtasks help.
- **Cost (H5, pre-registered as expected to fail):** the D arm spent ≈3.8×
  (P1) and ≈4.7× (P2) the tokens of the A arm, and took 6.3× / 2.1× the wall
  time. **H5 is falsified on the pilot**, as pre-registered.
- **Worker context (H4):** the largest worker request carried 7 451 prompt
  tokens (P2) — below the 20 k threshold. The Brief itself is 1 124–1 352
  bytes; the rest of the worker's context is OpenCode's own prompt plus the
  accumulated tool outputs.
- **Scope:** zero out-of-scope edits in all four runs; the workers touched
  exactly the one file per microtask they were allowed.

## 3. Tīrtha request metadata (D arm, from `proxy_requests.jsonl`)

Every worker request carried `{"mode": "low", "no_cache": true}`; the model
string was `auto`; the response reported `mode: "low"`.

| run | served_by | served_model_id |
|---|---|---|
| D/P1 | `Cerebras`, `deepinfra` | `openai/gpt-oss-120b`, `Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo` |
| D/P2 | `Cerebras`, `deepinfra` | `openai/gpt-oss-120b`, `Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo` |

**This is the important negative finding of the pilot:** even in `mode=low`
the gateway answers with *different base models* on different requests. There
is no fixed base model to attribute the result to. The D arm is therefore
labelled **"Tīrtha gateway, mode=low"** and never a model name.

## 4. Gate status

| Gate | Status | Evidence |
|---|---|---|
| G1 distinct ACP sessions in one process | ✅ | `harness/preflight_acp.py` → 2 distinct `sessionId`, close + delete OK |
| G2 plan compiler rejects invalid plans | ✅ | `validate_plan.py --selftest` → 6 invalid shapes rejected |
| G3 no `AGENTS.md` in the worktree or its ancestors; no hidden test in the Brief | ✅ | `agents_md_in_ancestors: []` in all 4 runs; `dry_run.py --selftest` leak check |
| G4 worker session deleted after the run | ✅ | `opencode session list` in the isolated home → empty |
| G5 worker output parses as JSON | ✅ | 3/3 worker answers parsed, 0 repairs needed |
| G6 worker configuration fixed and recorded | ✅ | same provider config, `model=auto` + `mode=low` in every record |
| G7 proxy recorded `mode=low` + `no_cache` | ✅ | `tirtha_sent = {"mode": "low", "no_cache": true}` in 11/11 records |
| G8 hidden tests fail on the bad patch, pass on the good patch | ✅ | `selftest_frozen.py` → negative fails, positive passes |

Two canary detectors were **retired by their own controls** (the model answered
`{"canary": null}` in the control where the token was present; the token-delta
control measured delta 0 in one run and 389 in another). A detector that cannot
fail in its own positive control is not a detector — the replacement is the
static ancestor scan above.

## 5. What this pilot does NOT show

1. **No quality claim.** 2 tasks, 1 run per cell, both arms 4/4 → ceiling
   effect. The main run needs ≥10 tasks and a corpus where the baseline
   actually fails sometimes.
2. **Provider confound.** Arm A ran on `opencode-go/minimax-m3.1-flash-free`
   (OpenCode account), arm D's worker on the Tīrtha gateway. The pilot
   therefore measures *architecture with different providers*, not a clean
   architecture effect.
3. **No fixed worker model.** Proven by §3 — two different base models inside
   one arm.
4. **The Tīrtha tool-call issue (2026-10-18) did not bite here**: 3/3 worker
   turns executed real tool calls, and the proxy recorded `checked: true`,
   `checked_by: schema` for the tool-call requests. It may still appear on
   other tasks.
5. **One attempt was superseded.** The first A/P1 run
   (`A-P1_mean-20261020T180423Z`) is excluded: its verdict was wrong for a
   measurement reason — the evaluation counted P2's hidden tests as P1's
   failures. It is kept in the artifacts, not deleted, and the collector marks
   it as superseded.
6. **Model availability forced two plan revisions** (both pre-registered
   before the run): `opencode/deepseek-v4.1-flash-free` returned
   `Rate limit exceeded` and `opencode-go/deepseek-v4.1-flash` returned
   `Go usage limit exceeded` (both hang instead of exiting), so the planner and
   baseline moved to `opencode-go/minimax-m3.1-flash-free`.

## 6. Next step (needs an owner decision)

- **main run**: 10 frozen real tasks, arms A vs C (decomposition only, same
  model) — this is the only design that isolates the architecture effect;
- **model-matched D**: run the D arm with the worker on the *same* model as the
  baseline, which requires either a local model or a Tīrtha key-level mode
  default;
- **cost**: the current D arm is 3.8–4.7× the tokens of A; before scaling to
  10 tasks, the planner call and the per-microtask overhead need a budget.
