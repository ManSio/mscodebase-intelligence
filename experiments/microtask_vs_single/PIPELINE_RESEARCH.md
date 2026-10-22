# Pipeline research — what already exists, and what must change (2026-10-21)

Research per the project protocol: every claim below is **Verified** (source
fetched/read) or explicitly **Unverified**. Third-party material is quoted
briefly; raw dumps stay outside the repository.

The architecture in question is: *Planner → Gate → Orchestrator → one-shot
sub-agent per step (clean room) → harness verifies (diff + tests) → next step.*

## 1. Verdict

**The architecture is not a hypothesis — it is a named, catalogued pattern family
with working implementations.** The parts the owner listed are all verified to
exist, and three of them are already official practice at GitHub. What is *not*
verified is the **cost arithmetic** ("2–4 k tokens per sub-agent, 5 steps ≈
20 k") in *our* runtime: it holds for a minimal worker loop, and does **not**
hold when the worker is OpenCode. That is the single most important finding of
this pass, and it is measured on our own runs.

## 2. Verified landscape

| Source | Status | What it gives us |
|---|---|---|
| `nibzard/awesome-agentic-patterns` | **Verified** (README read, Apache-2.0) | The pattern catalogue that names our design: `sub-agent-spawning`, `planner-worker-separation-for-long-running-agents`, `context-budget-as-a-governed-resource`, `deterministic-zero-llm-orchestration`, `deterministic-grader-in-the-loop`, `capability-escrow-receipt`, `llm-map-reduce-pattern`, `agent-circuit-breaker`, `budget-aware-model-routing-with-hard-cost-caps`, `subject-hygiene-for-task-delegation`, `tool-capability-compartmentalization`, `own-check-fault-injection`, `structured-output-specification`, `subagent-compilation-checker`, `working-memory-via-task-tracking` |
| `superfly/contextwindow` (Go, 100★) | **Verified** (README read) | "a low-level library for writing Go LLM agents"; its impetus is explicitly **multi-context agents**: many independent conversations, token-usage tracking, SQLite persistence, summary compression |
| `Antropath/minimal-agent` (93★, Apache-2.0) | **Verified** (README) | ~100-line ReAct core; "writes actions in code" (CodeAct) — a minimal worker loop |
| `codereindeer-dev/minimal-agent` | **Verified** (README) | single-file core with a `spawn_agent` tool, **context isolation**, depth limit ≤ 2, token counting + auto-trim, skills that inject only name+description until loaded |
| `averagejoeslab/nanoagent` (TS) | **Verified** (README) | budget from **real token counts** ("system prompt + tool schemas + output reserve. No magic constants"), eviction of whole turns only, never broken apart |
| `barun-saha/kodeagent` | **Verified** (README) | Planner + **Observer** that detects loops and stalled plans; "optimized for SLMs" |
| GitHub Copilot CLI (blog 2025-10-13 + changelogs) | **Verified** | **Session splitting** ("one session for planning, one for implementation, one for testing… fresh context → better focus"); **spec-kit** flow `spec.md → plan.md → tasks.md` with the checkpoint "specifications are split into tasks that are implementation-ready before delegation"; **an `agentStop` hook that always blocks ends the turn after 8 consecutive blocks**; `/worktree new` for isolated sessions; deferred tool loading per agent |
| Anthropic, *Building effective agents* (2024-12-19) | **Verified** | the canonical pattern list: prompt chaining with programmatic gates, routing, parallelization (sectioning/voting), **orchestrator-workers**, **evaluator-optimizer**; plus ACI advice ("we spent more time optimizing our tools than the overall prompt") |
| Anthropic, *How we built our multi-agent research system* (2025-06-13) | **Verified** | multi-agent (Opus 4 lead + Sonnet 4 subagents) beat single-agent Opus 4 by **90.2%** on an internal research eval; **token usage alone explains 80%** of BrowseComp variance; multi-agent burns **~15×** the tokens of chat; each subagent needs objective + output format + tool guidance + clear boundaries; **end-state evaluation**; subagent output to a filesystem, not through the lead |
| Anthropic, *Effective context engineering* (2025-09-29) | **Verified** | sub-agents may burn tens of thousands of tokens and return **1 000–2 000** tokens; "find the smallest set of high-signal tokens" |
| Anthropic, *Code execution with MCP* (2025-11-04) | **Verified** | 150 000 → 2 000 tokens (−98.7%) by loading tool definitions on demand and filtering results in code |
| Anthropic, *Advanced tool use* (2025-11-24) | **Verified** | Tool Search: −85% context, Opus 4 49% → 74%; **Programmatic Tool Calling**: 43 588 → 27 297 tokens (−37%), only the final output enters the context; Tool Use Examples: 72% → 90% |
| Magentic-One (arXiv:2411.04468) | **Verified** (abstract) | the closest published analogue to "the router re-plans and does not re-verify": Orchestrator + **progress ledger** + re-planning, with specialist agents |
| RouteLLM (arXiv:2406.18665) | **Verified** (abstract) | a learned router cuts cost **>2×** without quality loss and transfers across model swaps |
| `github/spec-kit` | **Unverified** (GitHub API 403, rate-limited) | the flow itself is documented in the GitHub blog; the repo was not fetched |
| Tom Jones / Tīrtha | **Verified** (dev.to + repo + his messages) | budget 4 000 chars/action and 2 000/crystal; "one knowing per crystal"; compounds 0.936¹² ≈ 0.45; the 1024-token output cap on the Base tier (ours: 10 of 998 responses exactly at 1024); his open work: multi-turn guards, apply_patch newlines, Qwen 3.8 Max as the top tier |

## 3. What the owner's template gets right (confirmed)

1. **Fixed context per sub-agent** — exactly the published sub-agent pattern, and
   the reason Anthropic's sub-agents return 1–2 k tokens.
2. **The diff/artifact is read by the harness, not carried in the answer** — we
   independently measured why this is mandatory: the Base tier cuts the answer
   at **1024 output tokens** (10 of 998 responses sat exactly there) and our own
   request for a diff in the answer caused both truncation and a 13× context
   blow-up (5.33 M → 0.40 M tokens after the change).
3. **The Gate must be deterministic code** — the catalogue's own name for it is
   *deterministic zero-LLM orchestration*; our `validate_plan` is that gate.
4. **The verifier must be code** — *deterministic grader in the loop*; a model
   verdict is a claim, not an observation.
5. **The receipt is a first-class artifact** — the catalogue calls it
   *capability escrow receipt*; we call it a receipt and it carries
   `cmd + exit code + sha256`.
6. **Fan-out of ~10 children with aggregation** — *LLM map-reduce*: children
   return pieces, the reduction happens once; Anthropic's programmatic tool
   calling is the same idea in a different dress.

## 4. Three corrections (measured on our own runs)

**C-1 — "2–4 k tokens per sub-agent" is a property of the *runtime*, not of the
pattern.** Our OpenCode-based worker measured: first request 1 074 prompt
tokens, but the *runtime floor* is ~4.5–5 k (OpenCode's system prompt + tool
schemas) and it grows to 7.5 k+ as tool outputs accumulate; a whole fix-task
run cost 37 k–698 k tokens. With a **custom minimal worker loop** (the
`minimal-agent` / `nanoagent` shape: one prompt + one tool schema + one file
excerpt) the 2–4 k band is realistic. ⇒ **To hit the band, the worker must be
our own loop, not an OpenCode session.** OpenCode stays the *thinking* runtime.

**C-2 — "5 microsteps ≈ 20 k tokens" requires the same change.** Under
OpenCode our 5–23-request runs cost 37 k–698 k. Under a minimal loop:
5 × (≈2 k brief + ≈1 k tool output + ≈1 k answer) ≈ 20 k. The claim is
*architecturally sound but runtime-dependent* — we must not publish it as a
general number.

**C-3 — The plan must be re-planned after each step.** The template plans
everything up front, which is only valid for *independent* steps. Step 2's brief
usually depends on step 1's *output*, which no up-front planner can know. The
published systems that survive long horizons all re-plan: Magentic-One
("Orchestrator … plans, tracks progress, and re-plans to recover from errors"),
Anthropic's orchestrator-workers ("subtasks aren't pre-defined, but determined
by the orchestrator"), and our own corpus has dependent steps (P2 = two files,
one of them depending on the other).

## 5. Gaps the template does not cover (and their published names)

| Gap | Published pattern / our fix |
|---|---|
| No loop guard | *agent circuit breaker*; Copilot CLI's 8-block cap; our `session/cancel` watchdog |
| No cost guard | *budget-aware model routing with hard cost caps*; our proxy answers 429 at $0.15 / 60 requests |
| No negative controls in the pipeline | *own-check fault injection*; our `no-op` and `block` task classes |
| "100% verified" not machine-checkable | *capability escrow receipt* — `cmd + exit + sha256`, and the router trusts the hash, not the prose |
| Provider answer cap | measured 1024 tokens on Base ⇒ the answer may only carry a receipt |
| Frontier model for the thinking step | unavailable here (paid Go models hang on `Go usage limit exceeded`); the planner is a free OpenCode-account model until that changes |
| Quality claim | Anthropic: 80% of the variance is tokens ⇒ any architecture comparison must be token-matched, or it measures spend, not architecture |

## 6. What this means for the next implementation step (no runs yet)

The pipeline to build is **not** "OpenCode + sub-agents"; it is:

```text
frontier-ish planner (OpenCode)  →  plan (code-gated)  →  re-plan per step
        ↓
custom minimal worker loop (Tīrtha Base, own HTTP client, 1–2 tool schemas)
        ↓
artifact on disk  →  code verifier (pytest + sha256)  →  receipt  →  router
```

with the budgets of `PIPELINE_DESIGN.md` (input ≤4096, answer ≤512, ≤3 steps
per unit of work) and the guards of §5. The OpenCode-based harness we built
stays useful as the *reference implementation* and as the measuring stick for
the new loop.
