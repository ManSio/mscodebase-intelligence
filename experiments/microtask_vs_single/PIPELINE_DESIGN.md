# Pipeline design — bounded microtask pipeline (2026-10-21)

Own synthesis. Every number below carries its referent (source file, or the
external publication it comes from).

## 0. The question

Build a pipeline where **one action = one microtask**, a sub-agent may itself
fan out to ~10 collectors/analysts, the result comes back **verified**, and
the top-level router does **not** re-verify — with every step's context inside
**512–4096 tokens**.

Answer: **yes, it is real, but only if three things are true**:
(1) the *answer* carries a receipt, not an artifact; (2) the aggregator is
**code**, not a model; (3) the chain of model steps per unit of work is ≤ 3.
Each of the three is forced by a measurement, not by taste.

## 1. The measured constraints

| # | Constraint | Measurement | Consequence for the design |
|---|---|---|---|
| C1 | The answer channel is capped | 10 of 998 proxy responses had **exactly 1024** completion tokens (Base tier); Tom reports 2048 on the escalated tier | An answer longer than that is **cut**. The artifact must never travel in the answer. |
| C2 | Artifacts in the answer inflate every later turn | our baseline arm peaked at **87 586** prompt tokens (above our own 79 k ceiling) and one run burned **5.33 M** tokens; p50 answer length is 55 tokens, p90 is 513 | The diff belongs on disk; the model reports a path + a hash. |
| C3 | Reliability compounds per step | per-call error 1.37% but **25.1%** of multi-step sessions carry ≥1 failure (our 4.7k-session corpus); Tom's bench: 93.6% per call, 0.936¹² ≈ 0.45 | Chain length per unit of work ≤ **3** steps (0.936³ ≈ 0.82). Retries belong to the router, not to the chain. |
| C4 | Error rate peaks at 8k–16k input tokens | our corpus: error rate peaks in the 8k–16k window (3.48%) | Per-step input budget ≤ **4096** tokens — well below the peak. |
| C5 | Aggregation in code, not in context | Anthropic PTC: 43 588 → 27 297 tokens (−37%), only the final output enters the context; Code Mode: 150 000 → 2 000 (−98.7%); Tool Search: −85% context, Opus 4 49% → 74% | The 10 children return artifacts; the **aggregator is Python**; only a ≤512-token digest reaches the parent. |
| C6 | The published multi-agent win is mostly a token-budget effect | Anthropic: token usage alone explains **80%** of BrowseComp variance; multi-agent uses ~15× the tokens of chat | Compare arms at **matched budget**, otherwise "more tokens" masquerades as "better architecture". |
| C7 | Billing makes unbounded runs expensive | our key is pinned to Max: **$1.90 in / $5.69 out per 1M**, $5/day cap, then fall back to Base | Our 5.33 M-token runaway ≈ **$10+ per run**. A bounded 3-step pipeline at ≤4096 tokens/step is ~**$0.02–0.10 per task**. The bound is now a billing requirement, not a preference. |
| C8 | Loops are the failure mode to expect | the C arm retried one unrunnable acceptance command for 400–1100 s (23 requests, 414 k tokens) | Every step needs a **budget + cancel** (we implemented `session/cancel` on a tool-call budget). |

## 2. The pipeline

```text
              ┌──────────────────────────── ROUTER (frontier model) ───────────────────────────┐
              │  task text only  ·  no code  ·  no diffs  ·  context ≤ 4096  ·  answer ≤ 512     │
              │  emits: microtask ids + acceptance commands + allowed files (a PLAN, not content)│
              └───────────────┬──────────────────────────────────────────────┬────────────────┘
                              │ one microtask at a time (writes are serial)    │
                              ▼                                              │
        ┌──────────────── MICROTASK LEAD (Tīrtha Base) ────────────────┐   │
        │ brief ≤ 4096  ·  answer ≤ 512  ·  ≤ 3 model steps             │   │
        │                                                                  │   │
        │  fan-out ≤ 10 children (Tīrtha Base), each:                    │   │
        │    brief ≤ 512  ·  answer ≤ 256  ·  returns ONE artifact + 1 line│   │
        │            (collector / analyzer / tester)                      │   │
        │                    │                                            │   │
        │                    ▼  AGGREGATOR = PYTHON (no model)             │   │
        │            filters/joins artifacts, emits ≤512-token digest      │   │
        │                    │                                            │   │
        │                    ▼  SOLVER (Tīrtha Base, 1 step)              │   │
        │            writes the change to the worktree (artifact on disk)  │   │
        │                    │                                            │   │
        │                    ▼  VERIFIER = CODE (pytest/lint/grep)        │   │
        │            exit code + artifact sha256  →  RECEIPT             │   │
        │                    │                                            │   │
        │                    ▼  GATE (1 cheap call)                       │   │
        │            {"ready": true, "receipt": "<id>"}  → router       │   │
        └────────────────────────┬────────────────────────────────────────┘   │
                                 ▼                                            │
              ┌──────────────────────────── ROUTER (frontier model) ───────────────────────────┐
              │  receives the receipt (not the content)  ·  re-plans only the next microtask    │
              └───────────────────────────────────────────────────────────────────────────────┘
```

### Roles, models and budgets

| Role | Model | Input budget | Answer budget | Returns |
|---|---|---|---|---|
| Router / planner | frontier (Claude/Codex class) | ≤ 4096 | ≤ 512 | plan: microtask ids, allowed file, acceptance command |
| Microtask lead | Tīrtha Base | ≤ 4096 (brief) | ≤ 512 | receipt id |
| Collector / analyzer (≤10) | Tīrtha Base | ≤ 512 | ≤ 256 | one artifact path + one factual line |
| Aggregator | **Python** | 0 | 0 | ≤ 512-token digest |
| Solver | Tīrtha Base | ≤ 4096 | ≤ 512 | writes the artifact; reports a path |
| Verifier | **Python** (pytest/lint/grep) | 0 | 0 | exit code + sha256 + the failing assertion if any |
| Gate | Tīrtha Base | ≤ 1024 | ≤ 256 | `{"ready": true, "receipt": "..."}` |

### The receipt (this is what "100% verified" has to mean)

```json
{
  "receipt_id": "r-3f9a2c",
  "microtask": "T1",
  "artifact": "runs/<run>/worktree/src/core/x.py",
  "artifact_sha256": "…",
  "verify": {"cmd": "python -m pytest tests/test_x.py::test_y -q", "exit": 0},
  "scope_ok": true,
  "issued_by": "verifier-code@v1"
}
```

The router's trust rule is **cryptographic and mechanical**: it trusts the
receipt's `sha256` + `exit: 0`, never the model's prose. If the artifact
changes after the receipt, the hash no longer matches and the router must
re-run the verifier. That is the only sense in which "the router does not need
to verify" is true — and it is exactly the difference between *verified* and
*claimed*. Tīrtha's own catalogue says the same: "a status field is a claim
about the world, not an observation".

### Why the fan-out of 10 children is affordable

Each child returns **an artifact + one line**, never prose. The aggregator is
Python: it filters, joins, sorts and emits a ≤512-token digest. The parent's
context therefore grows by ~512 tokens, not by 10 × (child answer). Without
that rule the fan-out is a context bomb — it is precisely what our baseline
arm did (one child's diff in the answer, re-sent every turn → 87 k tokens).

### Why 512–4096 is the right band

- 512 tokens is the **answer** budget: below the 1024-token provider cap with
  margin, and small enough that a child can return one fact per call.
- 4096 tokens is the **input** budget per step: below the 8k–16k band where
  our own corpus shows the error-rate peak (3.48%), and small enough that
  OpenCode's own tool surface plus a 1–2 kB brief fits inside it.
- The published reference points agree: Anthropic's sub-agents return 1 000–2 000
  token summaries, and the Tool Search pattern keeps a 50-tool setup at
  ~8.7 k tokens of context.

## 3. The guards the pipeline needs (from the corpora, ours and Zed's)

| Guard | Rule | Source |
|---|---|---|
| Step budget | cancel the step after N tool calls (we use `max_steps × 3`) | our C-arm loop (400–1100 s) |
| Output cap | never ask for a diff in the answer | 10/998 responses at exactly 1024 tokens |
| Numbered paste | strip `^\d+:\s?` prefixes from `oldString` before matching | 1/17 of our anchor-present failures |
| Stale after own edit | if an edit/write to the same file happened after the last read → force a re-read | 14/17 of our anchor-present failures |
| No prior read | if the target file was never read → force a read before the edit | our corpus: 59 edit failures with no completed read |
| Windowed read | if the last read was a window and the failed `oldText` matches inside it → force a **full** re-read | our Zed corpus: 53 of 62 call-level anchor-present failures |
| Refusal honesty | the "no change" and "blocked" classes must be in the corpus, or the pipeline is a yes-machine test | our corpus: `no-op` 6/6 and 6/6, `block` 5/5 — and both must keep being measured |

## 4. What the design costs, measured

| Unit of work | Model calls | Tokens | Wall time | Cost at Max rates |
|---|---|---|---|---|
| one microtask (lead + ≤10 children + solver + gate) | 3 + ≤10 | ≤ 30 k | ~60–120 s | ≤ $0.07 |
| one task = 3 microtasks | ~9–39 | ≤ 90 k | ~3–6 min | ≤ $0.2 |
| our measured baseline runaway (A arm, one task) | 50–81 | 5.33 M | 237–683 s | **≈ $10+** |

## 5. What "100% verified" cannot mean

- It cannot mean "the model said it is done" — that is a claim.
- It cannot mean "the checks we ran all passed" without knowing whether the
  checks can fail — a positive control cannot detect a yes-machine. That is why
  the corpus carries `no-op` and `block` tasks: they are the negative controls
  of the pipeline itself.
- It cannot mean "the base model is fixed": behind `tirtha/auto` the gateway
  served `Cerebras`, `deepinfra` and `llama-sambanova` (and `gpt-oss-120b` /
  `Qwen3-Coder-480B`) on different requests. The pipeline must therefore pin
  the *configuration* (model string, `mode`, `no_cache`) and record the model
  that actually served every request — which our proxy already does.

## 6. Open items, in the order they block

1. **Re-run the fix class with the receipt contract** (the diff no longer
   travels in the answer). The old numbers are contaminated twice over: the
   baseline's context blow-up was partly self-inflicted by our own prompt, and
   8 verdicts coincide with answers cut at the 1024-token cap.
2. **Wire the aggregator as code** (digest ≤512 tokens) — it is the only part
   that makes the 10-child fan-out affordable.
3. **Move the verifier to code** (pytest/lint + sha256) so the receipt is
   machine-checkable and the router can skip re-verification honestly.
4. **Decide the executor's tier**: with the key pinned to Max the cheap tier
   is no longer cheap for us; `mode=low` (Base, 1024-token cap) vs Max
   (2048) is now a *protocol* choice, not just a price choice.
