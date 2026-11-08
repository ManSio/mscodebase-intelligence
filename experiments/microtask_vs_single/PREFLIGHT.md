# Preflight record — 2026-10-20

No model was called in any command below. Raw output is reproduced verbatim.

## Commands and results

| # | Command | Result |
|---|---|---|
| P1 | `python experiments/microtask_vs_single/harness/validate_plan.py --selftest` | `SELFTEST: PASS (valid accepted; 6 invalid rejected; fallback accepted)` |
| P2 | `python experiments/microtask_vs_single/harness/selftest_frozen.py` | `SELFTEST: PASS (negative fails, positive passes)` |
| P3 | `python experiments/microtask_vs_single/harness/brief_builder.py --selftest` | `SELFTEST: PASS (T1=1101B/2files, T2=1124B/2files)` |
| P4 | `python experiments/microtask_vs_single/harness/dry_run.py --selftest` | `SELFTEST: PASS (dry run, no model calls, no hidden leakage)` |
| P5 | `python experiments/microtask_vs_single/harness/preflight_acp.py` | `ACP PREFLIGHT: PASS (2 distinct sessions, close, delete)` |
| P6 | `python experiments/microtask_vs_single/harness/freeze_manifest.py --check` | `VERIFY: PASS (22 files)` |
| P7 | `python -m ruff check experiments/microtask_vs_single/harness` | `All checks passed!` |

## Raw output

```text
$ python experiments/microtask_vs_single/harness/preflight_acp.py
INIT: agent='OpenCode' protocol=1
SESSIONS: ['ses_ea5aef676ffemf3NpDdIhAonzu', 'ses_ea5aef662ffe6Mi4ByK4PlXJKh']
CLOSE: OK
DELETE: OK (2)
ACP PREFLIGHT: PASS (2 distinct sessions, close, delete)
```

```text
$ python experiments/microtask_vs_single/harness/selftest_frozen.py
NEGATIVE: planted defects fail hidden tests (exit=1)
POSITIVE: known-good patch passes hidden tests
SELFTEST: PASS (negative fails, positive passes)
```

```text
$ python experiments/microtask_vs_single/harness/dry_run.py --selftest
P1_mean: 1 brief(s), [1103] bytes
P2_money: 2 brief(s), [1101, 1124] bytes
SELFTEST: PASS (dry run, no model calls, no hidden leakage)
```

## Gate status

| Gate | Status | Evidence |
|---|---|---|
| G1 distinct sessions in one process | ✅ verified (mechanical) | P5 |
| G2 plan compiler rejects invalid plans | ✅ verified | P1 |
| G3 worker cannot see `CANARY_AGENTS` | ⏳ untested — needs a model run | dry run shows no canary in Briefs, but the worker's own system context is unverified |
| G4 session deleted after the run | ✅ verified (mechanical) | P5 |
| G5 worker output parses as JSON | ⏳ untested — needs a model run | — |
| G6 worker model is fixed | ⛔ open for Tirtha, ✅ possible for the OpenCode fallback | Tirtha gateway exposes only `tirtha/auto` |
| hidden tests fail on a known-bad patch | ✅ verified | P2 (negative fails, positive passes) |

Gates G3, G5 and G6 cannot be closed without a model call. Per the standing
owner instruction, no model call was made here.
