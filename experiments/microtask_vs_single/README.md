# microtask_vs_single

**Status:** pre-registered; **not run**; Tirtha worker blocked.

## Question

Does a planner + isolated microtask workers pipeline produce better code than
one agent in one OpenCode session, at acceptable cost?

## What is frozen

- `frozen/repo/` — synthetic tinycalc corpus with two planted defects.
- `frozen/tasks/` — P1 (single-file) and P2 (multi-file, splits into two
  microtasks).
- `frozen/prompts/` — planner, worker, baseline, reviewer.
- `frozen/hidden/` — evaluation tests, not visible to the agent.
- `frozen/HYPOTHESES.md` — pilot gates G1–G6 and main hypotheses H1–H6.
- `frozen/MANIFEST.json` — hashes and model decisions.
- `frozen/plans/` — reference plans written by the designer as compiler test
  vectors. They are **not** the planner's output.
- `harness/validate_plan.py` — plan gate with self-test.
- `harness/brief_builder.py` — bounded Brief construction (≤8 kB, ≤3 reads).
- `harness/dry_run.py` — mechanical pipeline without any model call.
- `harness/acp_client.py` — minimal ACP transport (no secrets, no key handling).
- `harness/preflight_acp.py` — session lifecycle check.
- `harness/freeze_manifest.py` — manifest generator and `--check` verifier.
- `harness/selftest_frozen.py` — hidden-test negative and positive controls.
- `PREFLIGHT.md` — commands and raw output of the non-model preflight.

## Preflight status (no model calls)

`PREFLIGHT.md` holds the raw output. Verified mechanically: plan gate rejects
six invalid plan shapes, hidden tests fail on the planted defects and pass on a
known-good patch, Briefs stay under 8 kB, the dry run leaks neither hidden
tests nor frozen inputs, and one ACP process creates two distinct sessions
that can be closed and deleted.

Not verified yet: G3 (canary isolation inside a real worker), G5 (worker JSON
output) and G6 (fixed model for Tirtha). All three need a model call, which
the standing owner instruction forbids until the design is approved.

## What is not frozen yet

- The Tirtha worker arm. The gateway exposes only `tirtha/auto`; the API ignores
  `model` and picks the tier. This cannot satisfy the fixed-model gate.
- The Tirtha tool-call path. Tirtha's OpenCode page reports a known issue
  (2026-10-18): tool calls can arrive as plain text, so the agent may answer
  without executing anything.

## Tirtha options

| Option | What it means | Status |
|---|---|---|
| A. Postpone Tirtha | run A vs D-open (`opencode-go/deepseek-v4.1-flash`) for harness only | recommended for pilot |
| B. `tirtha/auto` + `mode=low` | product-level gateway comparison; no base-model attribution | valid only as a separate claim |
| C. Direct Tirtha API + custom tool loop | bypasses the OpenCode tool-call issue; worker is no longer OpenCode | more harness work |
| D. Local model | fixed model and hash, but none installed | separate arm later |

Do not silently replace D-tirtha with `auto`. A run with `auto` is a different
experiment.

## Pilot

- 2 tasks, arms A and D-open, 1 run per cell.
- Gates G1–G6 must pass.
- The pilot validates mechanics only; it is not evidence for H1–H6.

## Reproduce the freeze

```text
python experiments/microtask_vs_single/harness/freeze_manifest.py
python experiments/microtask_vs_single/harness/validate_plan.py --selftest
```

The manifest must be regenerated after any frozen input changes.
