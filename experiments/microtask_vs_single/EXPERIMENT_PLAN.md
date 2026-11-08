# microtask_vs_single — experiment plan

**Status:** pre-registered, pilot approved, not yet run.
**Date:** 2026-10-20 (revisions 2 and 3, same day, all before the first run).
**Question:** does a planner + isolated microtask workers pipeline produce better
code than one agent in one OpenCode session, at acceptable cost?

## 1. Frozen decisions

| Decision | Value |
|---|---|
| Pilot corpus | synthetic `frozen/repo` (tinycalc) |
| Pilot size | 2 tasks (P1, P2) |
| Main corpus | one real MSCodeBase module, frozen later |
| Planner model | `opencode-go/minimax-m3.1-flash-free` (revision 3) |
| Baseline model | `opencode-go/minimax-m3.1-flash-free` (revision 3) |
| Worker model (approved by owner) | `tirtha/auto` with `tirtha.mode=low`, `tirtha.no_cache=true` |
| Worker enforcement point | local proxy in front of `https://api.tirtha.ai/v1` (see §6) |
| Attribution | the D arm measures the Tīrtha gateway in low mode, never a named base model |
| Confound | A runs on the OpenCode account model, D's worker on Tīrtha — declared, not a clean architecture effect |
| Local worker | none installed; separate arm when available |
| Tool surface | planner: no write/edit/bash; baseline and worker: write/edit/bash; no `task`, no web, no MCP |
| Sessions | one ACP session per role; no `session/resume` or `fork` |
| Worktrees | one clean worktree per run; write tasks sequential in the pilot |
| Isolation | isolated `HOME`/`XDG_DATA_HOME` per role, `OPENCODE_DISABLE_PROJECT_CONFIG=1`, global MCP servers and global custom tools disabled by name |
| Known limit | the global config dir is NOT redirectable on Windows → the owner's global `AGENTS.md` is inherited by both arms (symmetric), see `frozen/HYPOTHESES.md` |
| Canary | random token planted in the control worktree's `AGENTS.md`; treatment worktrees have none |

## 2. Arms

| Arm | Architecture | Planner | Worker | Purpose |
|---|---|---|---|---|
| A | one session | — | — | baseline (pilot) |
| D | microtasks | OpenCode | `tirtha/auto`, mode low | treatment (pilot) |
| D-open | microtasks | OpenCode | `opencode-go/deepseek-v4.1-flash` | fixed-worker fallback if D is infrastructure-blocked |
| B | one session | — | Tirtha | model-only control, later |
| C | microtasks | OpenCode | OpenCode | decomposition-only control, main run |
| E | microtasks | OpenCode | local | local-model control, later |

The pilot runs **A and D**. Both arms share the same task, snapshot, public
tests, time cap, and tool policy; the treatment is the architecture. A and D
are not model-matched (different providers) — that is a known limitation, and
the report must state it: the pilot measures *architecture with different
providers*, not a clean architecture effect.

## 3. Pilot

### Tasks

- `P1` — single-symbol arithmetic mean fix.
- `P2` — multi-file money rounding; the planner must split it into two
  one-file microtasks with a dependency.

### Run matrix

| Task | A | D |
|---|---|---|
| P1 | 1 run | 1 run |
| P2 | 1 run | 1 run |

Plus one canary positive control session (G3). One run per cell is enough for
harness validation. It is **not** enough for a quality claim.

### Pilot gates

G1–G8 are frozen in `frozen/HYPOTHESES.md`. Any failure stops the main run.

### What the pilot proves

- ACP process/session lifecycle works.
- Plan compiler rejects bad plans.
- Briefs are bounded and workers stay in scope.
- Canary isolation works.
- JSON output is parseable.
- Session cleanup works.
- A and D can run on the same snapshot.

### What the pilot does not prove

- That microtasks improve quality.
- That Tirtha works.
- That the result generalizes beyond tinycalc.

## 4. Roles and decomposition

| Stage | Owner | Output |
|---|---|---|
| Intake | Python | clean worktree, baseline smoke, index |
| Plan | OpenCode planner | `plan.json` |
| Plan gate | Python `harness/validate_plan.py` | accept/reject |
| Brief | Python `harness/brief_builder.py` | one Brief per task |
| Execute | worker session | JSON + diff |
| Verify | Python | acceptance, lint, hidden tests only at evaluation |
| Integrate | Python + planner | merged diff, full test run |
| Review | OpenCode reviewer | accept/repair/reject |

Decomposition is **LLM-proposed, code-approved**. The planner never edits.
The compiler enforces:

- one symbol and one file per microtask;
- one acceptance command per microtask;
- acyclic dependencies;
- no test files in `files`;
- max 8 microtasks;
- fallback to `single_session` if the task cannot be split.

## 5. Metrics

Primary:

- hidden acceptance pass/fail;
- public acceptance command;
- lint/typecheck.

Secondary:

- total input/output tokens;
- max input tokens on any request;
- wall time;
- tool calls and retries;
- diff size and out-of-scope files;
- integration failures;
- `blocked` rate;
- human interventions.

Report per task and per arm. Do not publish a single aggregate without the
per-task table.

## 6. Tirtha treatment and the proxy

Verified on 2026-10-20:

- `GET https://api.tirtha.ai/v1/models` returns only `tirtha/auto`.
- Tirtha API docs: `model` is ignored; the gateway selects the tier.
- Tirtha API docs: `tirtha.mode` (`auto`/`low`/`value`/`max`) is a per-request
  body extension; `low` = Base only, never escalates.
- Tirtha API docs: every response carries a `tirtha` object with `served_by`,
  `checked`, `checked_by`, `escalated`, `mode`.
- Tirtha agents docs: known issue dated 2026-10-18 — OpenCode sessions can get
  a tool call as plain text.

Owner decision (2026-10-20): worker = `tirtha/auto` with `mode=low`; the
pilot is approved.

### 6.1 The proxy is the enforcement point and the instrument

OpenCode hides the raw provider response, so `served_by` / `mode` / usage
would be unobservable. A local proxy sits between OpenCode and
`https://api.tirtha.ai/v1`:

- it enforces `tirtha.mode=low` and `tirtha.no_cache=true` in the request
  body (documented API extensions) regardless of whether OpenCode propagates
  model options;
- it records, per request: path, `model`, `stream`, the enforced fields, the
  response status, the `tirtha` metadata object, and the token usage;
- it stores **no prompt content and no credentials** — only metadata and a
  body hash;
- it never writes the upstream key to disk: the key is read from the owner's
  global config into memory at start-up and used only as an `Authorization`
  header.

Because the proxy injects the treatment, every run records the fields it
actually sent — the treatment is verifiable after the fact, not assumed.

### 6.2 Model availability, measured (revision 3)

The originally frozen models turned out to be unavailable, and the CLI
**hangs instead of exiting** when the provider errors — a failure mode that
looks like a slow model. The log line is the only reliable signal:

```text
ERROR "stream error" providerID=opencode modelID=deepseek-v4.1-flash-free error.error="AI_APICallError: Rate limit exceeded"
ERROR "stream error" providerID=opencode-go modelID=deepseek-v4.1-flash error.error="AI_APICallError: Go usage limit exceeded"
```

Probe results (one call each, `opencode run "Reply with the single word OK."`):

| Model | Result |
|---|---|
| `tirtha/auto` | `OK` in 10.5 s |
| `opencode-go/minimax-m3.1-flash-free` | `OK` in 15.1 s |
| `opencode/deepseek-v4.1-flash-free` | hang >200 s (rate limit) |
| `opencode-go/deepseek-v4.1-flash` | hang >150 s (Go usage limit) |

Rule for the harness: a model is usable only after a probe that returned
output. A hang is a failure, not a slow start.

### 6.3 Consequences for the report

- The D arm is labelled **"Tīrtha gateway, mode=low"**. Never a model name.
- If the response metadata shows `escalated=true` in `mode=low`, that is a
  gateway-side inconsistency and must be reported as such.
- The known 2026-10-18 tool-call issue is expected to show up as
  `infra_tool_call_text` outcomes, not as `fail_quality`.

## 7. Artifacts

```text
frozen/
  HYPOTHESES.md
  MANIFEST.json
  tasks/
  plans/
  prompts/
  repo/
  hidden/
harness/
  validate_plan.py
  brief_builder.py
  dry_run.py
  acp_client.py
  preflight_acp.py
  freeze_manifest.py
  selftest_frozen.py
  proxy.py
  config_factory.py
  runner.py
runs/<run_id>/
  plan.json
  briefs/
  worker_outputs/
  diff.patch
  test.log
  usage.json
  proxy_requests.jsonl
  timeline.jsonl
```

`frozen/**` is committed. `runs/**` is not committed; only the summary and
manifest hashes go into the report.

## 8. Stop conditions

1. Any pilot gate G1–G8 fails.
2. The hidden-test harness cannot be shown failing on a known-bad patch.
3. A worker edits a test or a file outside its scope.
4. The canary is visible to a treatment arm, or the canary detector does not
   fire in its positive control.
5. The recorded worker configuration changes between runs.
6. The proxy did not record `tirtha.mode=low` for a worker request.
7. More than half of the D-arm runs end in an `infra_*` class — the A-vs-D
   comparison is then declared inconclusive and only an infrastructure verdict
   is reported.

## 9. Preflight (before the first LLM call)

```text
python -m pytest experiments/microtask_vs_single/frozen/repo/tests/test_smoke.py -q -p no:cacheprovider
python -m pytest experiments/microtask_vs_single/frozen/repo/tests/test_public.py::test_mean_basic -q -p no:cacheprovider      # expected fail
python -m pytest experiments/microtask_vs_single/frozen/repo/tests/test_public.py::test_total_half_up -q -p no:cacheprovider   # expected fail
python experiments/microtask_vs_single/harness/validate_plan.py --selftest
python experiments/microtask_vs_single/harness/selftest_frozen.py
python experiments/microtask_vs_single/harness/brief_builder.py --selftest
python experiments/microtask_vs_single/harness/dry_run.py --selftest
python experiments/microtask_vs_single/harness/preflight_acp.py
python experiments/microtask_vs_single/harness/proxy.py --selftest
python experiments/microtask_vs_single/harness/freeze_manifest.py --check
```

The first command must pass. The next two must fail for the right reason.
`validate_plan.py --selftest` must show both an accepted valid plan and a
rejected invalid plan. `selftest_frozen.py` must show the hidden tests failing
on the planted defects and passing on a known-good patch. `proxy.py --selftest`
must show the enforcement fields injected into a request body and the response
metadata captured, against a fake upstream (no network, no model call).

Current status and raw output: `PREFLIGHT.md` (2026-10-20). Gates G3, G5, G6
and G7 still require a model call and are therefore open.
