# Super protocol — the pipeline, specified (2026-10-21)

Own synthesis. Every number here was measured on this machine or on the
owner's LM Studio server; sources are in `PIPELINE_GEMMA.md` and
`PIPELINE_NATIVE.md`.

## 0. What the owner asked for

* every operation is a **microstep** (not only search/read/write);
* the pipeline is **autonomous**, **verified**, and **red-teamed**;
* it must run **inside OpenCode** as an internal mechanism;
* the orchestrator (cloud OpenCode) gets the **result only** and does not
  participate;
* the executor is our own **Gemma 4 26B A4B (QAT)** on our LM Studio server;
* locally we keep the orchestrator, the verifier and the filesystem, with
  **2 concurrent worker streams**.

## 1. The microstep taxonomy (one tool each)

| kind | action | tools | input budget | observation | who |
|---|---|---|---|---|---|
| `locate` | find where something is | `search_files` | ≤512 | ≤20 hits `path:line` | model |
| `read` | look at code | `read_file` | ≤512 | ≤30 numbered lines | model |
| `write` | change a file | `write_file` / `patch_file` | ≤2048 | 1-line ack | model |
| `exec` | run something | `run_command` | ≤512 | exit code + first error line | model |
| `output` | look deeper at a run | `read_output` | ≤512 | ≤40 lines | model |
| `decide` | choose the next step | — | ≤512 | ≤512 JSON | model |
| `verify` | claim a file is done | — | ≤512 | ≤512 JSON | model |
| `handoff` | pass a digest upward | — | ≤512 | ≤512 JSON | model |

**Plus the code layer** (deterministic, never a model): `plan` (code-first),
`gate` (plan check), `measure` (run the acceptance command), `slice` (find the
relevant code), `apply` (apply a proposed diff), `verify` (decide pass/fail),
`receipt` (mint the receipt).

## 2. The ladder

```text
L0  OpenCode (cloud, free account model)   →  one tool call: pipeline_run(task)
L1  our loop (code)                        →  plan → gate → schedule → collect receipts
L2  micro-agents (Gemma 4, one tool each)  →  measure → write → measure → write
L3  code                                   →  run tests, apply diffs, mint receipts
```

The L0 agent never sees a transcript, an artifact or a microstep. It receives
**receipts + a ≤2 k summary**, so "the router does not verify" is literally
true: the receipts are machine-checked and hash-bound.

## 3. The protocol of one microstep

```text
INPUT   goal (1 sentence) + context (≤2 k, shrunk to fit) + allowed scope
STEP    one action; at most 2 model turns; the action is mandatory
OUTPUT  observation → file (never into the parent's context)
RECEIPT the model returns ≤512 tokens: status, files, tests — no artifact
GUARDS  path scope · one writer per file · test files read-only and restorable ·
        prompt/output/step/wall budgets · the verdict comes from code
```

## 4. Measured facts that shaped it

| finding | measurement | consequence |
|---|---|---|
| the answer channel is capped | Tīrtha Base: 10 of 998 answers at exactly 1024 tokens | the answer carries a receipt, never a diff |
| a model reasons in `content` | Gemma 4 answered prose ("I haven't found the bug yet"), no diff, twice | a **second phase**: "now output ONLY the diff" |
| `tool_choice` is not supported | the backend rejected it (400 → our fallback) | the action is requested in the prompt, and the harness *applies* a diff instead of trusting a tool call |
| the model needs the right slice | with the file head it said "seems to be a diagnostic report script"; with the harness-resolved slice it diagnosed the failing assertion | the **code layer** resolves the relevant function (identifiers of the failing test) |
| a minimal loop is cheap | one tool call = **147 tokens** | 5 microsteps ≈ 3–4 k tokens |
| OpenCode's floor is heavy | ≈4 500–5 000 tokens per session | the executor must be *our* loop, not an OpenCode session |
| the server drops long requests | WinError 10054 / 10051 on 1.5–3 k output tokens; 300 s timeout | **throughput is the practical blocker** (see §6) |

## 5. Red team (executable, 13/13 defended)

`pipeline/red_team.py` — each attack must be *refused*, not merely survived:

| # | attack | guard |
|---|---|---|
| A1 | write outside the repo (`../`) | `resolve()` + `is_relative_to` |
| A2 | write a test file | test files are not writable |
| A3 | write outside the microtask's scope | one writer per file |
| A4 | write by absolute path | same as A1 |
| A5 | write through a symlink pointing outside | `resolve()` catches it |
| A6 | tamper with the test to make it green | tests are restored from the pristine copy; the run is invalid |
| A7 | unknown tool | refused |
| A8 | huge command output | summarised (exit + first error), never inlined |
| A9 | output slice | capped at 40 lines |
| B1 | the model loops on a tool | ≤2 model turns per microstep |
| B2 | the model edits a test through the loop | refused and recorded |
| B3 | oversized prompt | refused before the model call |
| B4 | the model forges a receipt | receipts are minted by the harness; a model claim is only data |

## 6. Measured state of the live path (2026-10-21, our LM Studio server)

* the pipeline **runs end to end**: plan → measure → brief → write → apply → verify → receipt;
* it produced **machine-checked receipts** with the exact failing test and the artifact hash;
* the red team is green (13/13);
* the **executor did not solve the real bug** on `17e65663b7_health` (it diagnosed the failing assertion but did not produce a diff within the budget) and on `e7dc645652_project_resolution` the **server reset the connection** mid-request (WinError 10054, then 10051);
* throughput: ≈150–300 s per model call ⇒ 24 steps ≈ 1–2 h per task — **too slow for a run**.

⇒ The blocker is the **executor/server**, not the protocol. Three concrete
levers, in order of expected effect:

1. **Use the MTP drafter** that is already on the server
   (`gemma-4-26b-a4b-it-qat-mtp`) — the QAT model card requires the drafter to
   be QAT at the same precision; speculative decoding should cut the per-token
   latency that dominates the step time.
2. **Cut the output budget of the write step** (reasoning in `content` is the
   cost): cap `max_tokens` at 512 and accept a two-phase answer, or ask for a
   *unified diff only* with a hard "no analysis" instruction.
3. **Compare executors on the same protocol**: our own loop against the
   metered gateway (`Qwen3-Coder-480B`, which our proxy measured at ≈$0.0004 per
   request) — that is a controlled A/B of the executor, at the cost of a
   metered run, and it separates "Gemma 4 cannot" from "our server is slow".

## 7. Integration into OpenCode

* `pipeline/mcp_server.py` — MCP stdio server exposing one tool, `pipeline_run`.
* `proposals/opencode.jsonc.fragment` — provider `lmstudio-remote`
  (`http://192.168.2.5:1234/v1`, model `google/gemma-4-26b-a4b-qat`,
  `limit.context 8192`), the `mcp.pipeline` entry, and the agents.
* `proposals/agent-local-executor.md` (`steps: 4`), `proposals/agent-micro-worker.md`
  (`steps: 2`, `hidden: true`) — the OpenCode-native variant, for comparison.
* The orchestrator agent: `model: opencode-go/minimax-m3.1-flash-free` (the only
  free account model that answers reliably here; probes in
  `PIPELINE_NATIVE.md`).

**Not applied to the global config** (it is the owner's file): the fragment is a
proposal; the only change we made was switching the global `model` off
`tirtha/auto` (backup: `opencode.jsonc.bak-20261021`).
