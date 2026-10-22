# Frozen hypotheses — microtask_vs_single

**Frozen at:** 2026-10-20, before any run.
**Revision 2 (2026-10-20, still before any run):** owner chose the worker as
`Tirtha auto + mode=low` and approved the pilot. The revision changes the
worker model, adds the proxy as the enforcement/measurement point, and adds the
canary positive control. No run had been executed at the time of this
revision, so freeze-before-look is preserved.
**Revision 3 (2026-10-20, still before any run):** the frozen planner/baseline
model was measured to be unavailable, and the role assignment changed:

- `opencode/deepseek-v4.1-flash-free` → `AI_APICallError: Rate limit exceeded`
  (the CLI then hangs instead of exiting);
- `opencode-go/deepseek-v4.1-flash` → `AI_APICallError: Go usage limit exceeded`;
- `opencode-go/minimax-m3.1-flash-free` → answers in ~15 s;
- `tirtha/auto` → answers in ~10 s.

Planner and baseline therefore run on `opencode-go/minimax-m3.1-flash-free`; the
worker stays on `tirtha/auto` with `mode=low` (owner's choice). No run had been
executed at the time of this revision, so freeze-before-look is preserved.
**Revision 4 (2026-10-20, after the A/P1 attempt, before any treatment run):**
the canary detectors were retired by their own controls, the isolation check
became a deterministic ancestor scan, hidden evaluation became task-scoped,
and worktrees moved outside the repository. The first A/P1 attempt is kept as
a superseded artifact (its verdict was wrong for a measurement reason: it
counted P2's hidden tests as P1's failures).
**Revision 5 (2026-10-20, after the pilot, before any further run):** the pilot
and the external research (Anthropic's multi-agent post, RouteLLM, Tīrtha's own
`docs/measured.md` and catalogue) force six protocol changes, all pre-registered
before the next run:

1. **Token-matched comparison.** 80% of the variance in the published
   multi-agent result is explained by tokens spent (Anthropic, 2025-06-13), so
   the main run compares A-with-budget against D-with-budget; the token ratio is
   a first-class metric, not a footnote.
2. **A corpus that contains failures.** Mutation-seeded defects in our own
   modules (the hidden test is the module's own test file). "A crystal cannot
   help where the model is not going to make the mistake" — our 4/4 pilot
   measured nothing.
3. **Three task classes:** `fix`, `no-op` (nothing is broken — the correct
   answer is to change nothing), `legitimate-block` (the honest answer is
   `blocked`). A corpus without the last two is a yes-machine test.
4. **Two controls:** the `D-direct` arm (worker talks to `api.tirtha.ai` with no
   proxy and no injected body fields) is the control for our own instrument,
   which otherwise reshapes the input; and the corpus gets three paraphrase
   controls (must hit) and three out-of-domain controls (must return NONE).
5. **≥2 runs per cell; report the floor and the partition**, not the total.
6. **Refuse to print a score when a control fails** (negative + positive
   control of the hidden-test instrument, and a non-empty population).

**Revision 6 (2026-10-20, before the batch):** the owner's Tīrtha dashboard
showed the key's real limits — **10 000 free requests/month (9 685 left)**, not
the 100 quoted in Tīrtha's own post — so the scale-up is unblocked. The key's
routing mode is `low`; our per-request records confirm `mode=low` on 173/173
requests, `escalated=false` on all of them and `cache_eligible=false` (the
`no_cache` we inject works). The dashboard's 315 requests include the owner's
own Tīrtha traffic (the key is the default model of their OpenCode), so
**per-run attribution must come from our proxy, not from the dashboard**.

Model roles follow the owner's rule "keep Claude or Codex for the thinking,
send the building to Tīrtha": the **planner** is a separate, stronger model and
the **executor** is Tīrtha. In this environment no Claude/Codex is reachable —
`opencode-go/claude-haiku-5-5` times out at 120 s (the Go plan's paid models
are blocked by `Go usage limit exceeded`, and the CLI hangs instead of
failing) — so the planner is `opencode-go/minimax-m3.1-flash-free`, the only
account model that answers. The rule (thinking ≠ building) is satisfied; the
specific planner model is an environment constraint, recorded as such.

Batch: 24 corpus tasks × arms A and C, one run each, then a second run in the
contested cells only. Classes are reported separately: `fix` (quality),
`noop` (must change nothing — a yes-machine fails it), `block` (the honest
answer is `blocked`).

**Status:** pre-registered, pilot approved (4 runs) and executed; main run
blocked on the revised corpus.

## Scope split

The 2-task pilot is **not** a test of H1–H6. It only validates the harness and
the isolation mechanism. No quality claim is allowed from the pilot.

The main experiment (10 tasks) tests H1–H6.

## Pilot arms (revised)

| Arm | Architecture | Planner | Worker |
|---|---|---|---|
| A | one OpenCode session | — | — (single session does the task) |
| D | microtasks | `opencode-go/minimax-m3.1-flash-free` | `tirtha/auto` with `tirtha.mode=low` |

Cells: A/P1, A/P2, D/P1, D/P2 — one run each.

A and D use **different model families** (OpenCode account vs Tīrtha gateway).
That confound is declared in advance: the pilot measures architecture with
different providers, not a clean architecture effect. A model-matched main
run (both arms on one gateway) is required before any quality claim.

## Pilot gates (must pass before the main run)

| # | Gate | Falsifier |
|---|---|---|
| G1 | One `opencode acp` process creates distinct sessions | two runs share a session ID |
| G2 | Plan compiler rejects an invalid plan (2 files, cycle, missing acceptance) | invalid plan is accepted |
| G3 | The worker sees no rule file: the worktree and every ancestor directory up to the drive root contain no `AGENTS.md`, and the Brief contains no hidden-test path | an `AGENTS.md` is found in the ancestor chain, or the Brief contains `hidden` |
| G4 | Worker session is deleted after the run | session remains in `opencode session list` |
| G5 | Worker output parses as JSON without repair | parser needs prose stripping or retry |
| G6 | Worker configuration is fixed and recorded for every run | the recorded config differs between runs |
| G7 | The proxy recorded request body carries `tirtha.mode=low` and `no_cache=true` | either field is missing |
| G8 | Hidden tests fail on the known-bad patch and pass on a known-good patch | either side of the control is silent |

Any failed gate stops the main run. A failed gate is a result, not a reason to
loosen the gate.

### G6 — what "fixed" means for a gateway-routed model

`Tīrtha` selects the tier itself; `model` is ignored and `auto` is the only
published model id. The gate therefore fixes the **request configuration**, not
a base-model identity:

- model string: `tirtha/auto`
- `tirtha.mode`: `low` (Base only, never escalates)
- `tirtha.no_cache`: `true`
- enforcement point: the local proxy that forwards to `https://api.tirtha.ai/v1`

The proxy stores the response metadata of every request
(`served_by`, `checked`, `checked_by`, `escalated`, `mode`) in the run
artifacts. Consequence for the report: the D arm measures **the Tīrtha gateway
in low mode**, never a named base model. Any statement about a specific model
is forbidden (see H3).

## Main hypotheses

| # | Hypothesis | Falsifier | Expected |
|---|---|---|---|
| H1 | Microtasks (D) beat single-session (A) on multi-file tasks | D ≤ A on pass rate | open |
| H2 | Decomposition alone helps: C > A | C ≤ A | open |
| H3 | Fixed-worker D is not worse than OpenCode-worker C by more than 20% | D < C by >20% | **not testable in this pilot** — `tirtha/auto` has no fixed base model, so D and C are not comparable as model arms |
| H4 | Worker per-request context stays below 20k input tokens | >30k on any worker request | open (worker side measured at the proxy) |
| H5 | D total cost is at most A + 30% | D > A + 50% | **expected to fail** |
| H6 | D has at most 1 integration failure per 10 tasks | >3 per 10 | **expected to fail** |
| H7 | At **matched token budget**, C (microtasks, same model as A) is not worse than A on the fix-class tasks | C < A on the fix class at equal tokens | open — this is the only H that isolates the architecture |
| H8 | The proxy does not change the outcome: D-proxy and D-direct agree on the fix class | the two disagree on ≥2 of 10 tasks | open — instrument control |

H5 and H6 are deliberately weak: decomposition adds planner calls, repair
loops, and merge work. If the experiment reports only wins, it is confirmation
bias, not a result.

### Known contamination: the global config directory cannot be isolated

Measured on 2026-10-20: OpenCode loads the owner's global config directory
(`~/.config/opencode`) **even when `HOME`, `USERPROFILE` and `XDG_CONFIG_HOME`
point to an isolated directory**. Evidence: the `available_commands_update`
notification of an isolated session listed the global skills
(`agentic-eval-lab`, `pitfalls-registry`, …) and the log reported duplicate
skill names from `C:\Users\misha\.config\opencode\skills`. The isolated
`HOME` does work for the data directory (the session database was created
inside it), but not for the global config directory.

Consequences, declared before the run:

1. The global **custom tools** and **skills** are available to every session of
   both arms (the harness disables the two known ones by name: `gate`,
   `recall`). The global `AGENTS.md` *rules*, however, are **not** injected:
   `AGENTS.md` is discovered by walking up from the project directory, and the
   global config directory is not an ancestor of the worktree. Measured: an
   isolated session reported `tokens_input = 4 480` (and 6 275 in an earlier
   control) while the global `AGENTS.md` alone is 80 549 bytes (≈20 k tokens).
2. The canary detectors were tried and **both were rejected by their own
   controls**:
   - the model-side copy test answered `{"canary": null}` in the control
     where the token was in the context;
   - the token-delta test measured `plain = 4 856` vs `with AGENTS.md =
     4 856` (delta 0) in the second control, while the first control showed a
     389-token delta for the same two variants — the counter's noise is of the
     same order as the effect.
   A detector that cannot fail in its own positive control is not a detector
   (§19.3), so both were retired. The detector that replaced them is
   **deterministic and static**: OpenCode discovers `AGENTS.md` by walking up
   from the project directory, so the harness checks that the worktree and
   every ancestor directory up to the drive root contain no `AGENTS.md`
   (`agents_md_in_ancestors`), and that the Brief contains no hidden-test
   path. Worktrees are therefore created **outside the repository** at
   `<repo-parent>/mscodebase-microtask-runs/<run_id>/worktree` — persistent,
   never `%TEMP%` (§21.5).
3. The inherited context is measured per run: `session.tokens_input` for the
   OpenCode-account roles (baseline ≈ 4.5–4.9 k for a trivial prompt, 7 270
   for the full baseline prompt) and `usage.prompt_tokens` at the proxy for
   every worker request.
4. H4 is therefore split: the Brief size is bounded by construction (≤8 kB,
   ≤3 files), while the *total* request context is measured per request and
   reported, not assumed.

## Outcome taxonomy (pre-registered)

Every run ends in exactly one class:

| Class | Meaning | Counts for H1–H6? |
|---|---|---|
| `pass` | hidden acceptance passed | yes |
| `fail_quality` | hidden acceptance failed, no infrastructure fault | yes |
| `blocked` | the agent reported that it cannot proceed | no — reported separately |
| `invalid_plan` | the planner produced a plan the compiler rejected | no — agent fault, not a quality signal |
| `invalid_scope` | the agent edited tests or files outside the allowed set | no — run is void, diff not merged |
| `infra_tool_call_text` | the gateway answered in plain text instead of executing a tool call (known Tīrtha issue, 2026-10-18) | no — infrastructure fault |
| `infra_invalid_json` | the agent output could not be parsed as JSON | no |
| `infra_timeout` | the session exceeded the time cap | no |
| `infra_provider_error` | provider/auth/rate error | no |

**Rule:** if more than half of the D-arm runs end in an `infra_*` class, the
pilot produces **no quality claim for the D arm** — only an infrastructure
verdict about the gateway, and the comparison A-vs-D is declared inconclusive.

## Controls

- Positive: P1 must pass in both A and D.
- Negative: an impossible task must fail in both A and D.
- Plan gate: an invalid plan must be rejected (G2).
- Test harness: a known-bad patch must fail a hidden test, a known-good patch
  must pass (G8).
- Canary: the isolation detector must fire in a positive control (canary
  present, config dir shared) and stay silent in the treatment arms.
- Proxy: the recorded request body and the recorded response metadata are the
  evidence for G7 and for the attribution caveat.

## Stop conditions

1. The canary detector does not fire in its positive control — G3 is
   `untested`, not `passed`, and the isolation claim is withheld.
2. The proxy does not record `tirtha.mode=low` — the treatment did not happen,
   and the run is void.
3. If G1–G8 fail, do not start the 10-task run.
4. If a worker edits tests or files outside scope, the run is invalid and the
   diff is not merged.
5. `tirtha/auto` must never be described as a specific base model.
