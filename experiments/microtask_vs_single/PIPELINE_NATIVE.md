# Native pipeline inside OpenCode (2026-10-21)

Own synthesis. Every OpenCode capability below was **verified against the
installed binary and `opencode debug config`** (config-only checks, no model
calls) or against the OpenCode docs (last updated 2026-10-20).

## 0. Decisions taken (owner, 2026-10-21)

| decision | value | note |
|---|---|---|
| **executor** | **Gemma 4 26B A4B (QAT) on our own LM Studio server** `192.168.2.5:1234` | verified live: tool-calling works, one worker turn = **147 tokens** |
| **orchestrator ("thinking")** | **a free OpenCode-account model**: `opencode-go/minimax-m3.1-flash-free` | probe table below; the only free model that answers reliably here |
| **Tīrtha** | **off for now** | removed from the pipeline; the global OpenCode model was switched away from `tirtha/auto` (backup: `opencode.jsonc.bak-20261021`) so the daily driver stops spending the prepaid credit |
| **parallelism** | 2 worker streams locally; the server should still be loaded with an explicit `--parallel 2` | "standard settings" = 4 slots, and LM Studio's `n_parallel` has three known bugs (#2061, #1714, #2262) ⇒ assert `n_slots` in the engine log |
| topology | MCP-native (one tool) as the target; OpenCode-native agents as the simpler fallback | see §2 |

### Free-model probe (2026-10-21, `harness/probe_model.py`)

| model | verdict |
|---|---|
| `opencode-go/minimax-m3.1-flash-free` | **USABLE in 12.5 s** ← chosen for the orchestrator |
| `opencode-go/beam-free` | answered in 9.0 s but not with the expected token (not used) |
| `opencode-go/longcat-2.5-preview-free` | **TIMEOUT** (>75 s) |
| `opencode-go/muse-spark-1.2-contributor` | **TIMEOUT** (>75 s) |
| `opencode-go/claude-haiku-5-5` (metered) | **TIMEOUT** (>120 s) — the Go plan's usage limit hangs the CLI instead of failing |
| `opencode/deepseek-v4.1-flash-free` | `Rate limit exceeded` (server-side) |
| `opencode-go/deepseek-v4.1-flash` (metered) | `Go usage limit exceeded` |

**Rule adopted:** a model counts as usable only after a probe that *returned an
answer*; a hang is a failure, not a slow start. This is why the free tier must
be probed before the pipeline depends on it.

### Consequence of the free orchestrator: the plan must be code-first

A weak planner is a real risk — our own data: the Tīrtha planner (a 480B
coder) returned an **empty/fallback plan twice**, and the arm then did nothing
while looking "done". Therefore the pipeline's plan is produced by **code**
(deterministic skeleton: one microtask per candidate file, in order) and the
model may only *refine* it (goal wording, ordering, acceptance). If the model
refinement fails or is refused, the code plan stands. This is the catalogue's
*deterministic zero-LLM orchestration* applied to the one step that must not
depend on a cheap model.

Target (owner's words): *OpenCode (cloud) is the top orchestrator and only
receives the final result; a local 8k model does all the work; sub-agents get
4096, micro-agents 2048; the whole thing must work as an internal mechanism of
OpenCode, without hacks.*

## 1. What OpenCode already gives us (verified, no hacks needed)

| Native mechanism | Verified form | What it buys us here |
|---|---|---|
| **Nested sub-agents** | `subagent_depth: 2` is accepted and resolved by the runtime (key present in the binary; value confirmed via `opencode debug config`) | sub-agent → micro-agent, i.e. the 4096/2048 ladder |
| **Per-agent model** | `agent.<name>.model` resolved (`local-executor: mode=subagent model=… steps=4` confirmed) | bind the top to a cloud model and the workers to a local one |
| **Per-agent step cap** | `agent.<name>.steps` resolved; docs: at the limit "the agent receives a special system prompt instructing it to respond with a summarization of its work" | the loop guard, natively (no `session/cancel` hack needed) |
| **Who may spawn whom** | `permission.task` with glob patterns, last match wins; `deny` removes the agent from the Task tool description entirely | the orchestrator may spawn only `local-*`; micro-workers may spawn nothing |
| **Internal agents** | `hidden: true` — "still be invoked by the model via the Task tool if permissions allow", invisible in the menu | our internal workers stay out of the user's UI |
| **MCP as the integration surface** | local/remote servers, per-agent enablement via `permission`/`tools` globs (`"mypipeline_*": true`) | the pipeline as **one tool**; OpenCode sees one tool, not ten |
| **Local model providers** | `llama.cpp` documented with `baseURL: http://127.0.0.1:8080/v1` and **`models.<id>.limit.context` / `limit.output`**; also LM Studio, Ollama (`num_ctx` tip: "start around 16k - 32k"), Atomic Chat, NVIDIA NIM | we can *declare* the 8k/4k/2k budgets in the model definition |
| **A separate small model** | `small_model` accepted and resolved | a local 1.5B can serve OpenCode's own title/summary calls, off the metered model |
| **Tool-surface compartmentalisation** | per-agent `permission` (read/edit/glob/grep/list/shell/task/webfetch/lsp/skill/question/**doom_loop**), glob patterns per tool | micro-workers get `read`/`edit`/`shell` on one file, nothing else; `doom_loop` is OpenCode's own stuck-recovery |
| **Deferred tool loading** | `defer_loading` present in the binary | per-agent tool catalogue without loading all schemas into context |

**Conclusion: the ladder, the guards, the model routing and the isolation are
all native. The only thing OpenCode does *not* give us is a context budget
below its own runtime floor (see §3).**

## 2. Two topologies, and which one is "without hacks"

### A. OpenCode-native (agents + Task tool)

```text
primary "orchestrator"        model: cloud (Claude/Codex class)   ← sees only the receipt
  └─ Task → subagent "local-executor"   model: local 8k   steps: 4
       └─ Task → subagent "micro-worker"  model: local 8k   steps: 2   hidden: true
            └─ writes the artifact, returns a receipt ≤512 tokens
```
Config: `subagent_depth: 2`, `permission.task` globs, per-agent `steps` and
`model`. Nothing to hack; three markdown files.

### B. MCP-native (the pipeline as one tool) — **recommended**

```text
OpenCode (cloud, primary)  ── one tool call: pipeline_run(task)
                                    │
                                    ▼
                     local MCP server (stdio) — deterministic code
                     plan → code gate → brief → executor loop → code verifier → receipt
                                    │  (executor = our own minimal loop against a local 8k model)
                                    ▼
                     receipt + ≤2k summary  ──► back to OpenCode
```

Why B is the one that matches the owner's requirement ("OpenCode gets the
result and does not participate"):

* **OpenCode's context stays clean**: it sees one tool, one receipt, one short
  summary — never the 10 children's artifacts, never the transcripts.
* **The orchestration is code, not a prompt** (the catalogue's *deterministic
  zero-LLM orchestration*), so the gate, the verifier, the budgets and the
  cost cap cannot be argued away by a model.
* **The context budget becomes real**: the executor is *our* loop (1 prompt +
  1–2 tool schemas + 1 file excerpt), so the floor is ~1.5–2 k tokens instead
  of OpenCode's ~4.5–5 k.
* **It composes with A**: the MCP server can also spawn OpenCode sub-agents
  over ACP (we already wrote an ACP client) for the levels that benefit from
  OpenCode's toolset.

Cost of B: one more moving part (~200 lines) and the MCP tool's own schema
(~200–400 tokens in OpenCode's context — acceptable).

## 3. The measured blocker: OpenCode's runtime floor

From our own runs (proxy records): an OpenCode request with a trivial prompt
still carried **~4.5–5 k tokens** (system prompt + tool schemas), growing to
**7.5 k** once tool outputs accumulate; p50 answer length 55 tokens, p90 513.

| level | owner's budget | OpenCode-native (A) | MCP-native (B) |
|---|---|---|---|
| micro-worker | 2048 | **impossible** (floor alone ≈4.5 k) | fits: floor 1.5–2 k + brief 0.3–1 k |
| sub-agent | 4096 | **impossible** (floor + brief >4 k) | fits: floor + brief + ≤2 k digest |
| local executor | 8192 | fits only for a micro-level brief | fits comfortably |
| orchestrator (cloud) | — | sees receipt only | sees receipt only |

⇒ **The 8k/4k/2k ladder is real only in topology B** (our own minimal loop) or
with a ≥16k local model in topology A. This is a property of the runtime, and
we measured it rather than assuming it.

## 4. The hardware reality for a local model (measured)

| item | value |
|---|---|
| RAM | 15.4 GB total, **5.2 GB free** |
| CPU | AMD Ryzen 5 5600H, 6 cores / 12 threads |
| GPU | integrated only (0.5 GB) — no CUDA |
| llama.cpp server | **present** (`…\Zed\extensions\mscodebase-intelligence\llama_msvc\llama-server.exe`) |
| local GGUFs on disk | only embedders (BGE-M3, e5-small) — **no code model** |

Consequences:

* The model in OpenCode's own llama.cpp example (`qwen3-coder:a3b`, 30B-A3B,
  128k ctx) **does not fit** (≈18–20 GB at Q4) and would be CPU-only anyway.
* A 7–8B coder at Q4 (≈4.7–5.2 GB) fits only if nothing else runs, and on
  6 cores it would give ~5–15 tok/s ⇒ a 2 k-token step takes 3–10 minutes.
* A 1.5–3B coder at Q4 (≈1 GB) is the only *practical* local executor
  (~20–30 tok/s, ~1–2 min per step) — usable, but far weaker than what the
  gateway serves us.
* The gateway measured `Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo` and
  `openai/gpt-oss-120b` at **≈$0.0004 per request**, 1 061–7 451 prompt tokens
  per request.

⇒ **Recommendation: the executor should be the gateway by default; the local
model is the offline/privacy option, and a 1.5–3B local model is a good
`small_model` for OpenCode's own title/summary calls** (keeps those off the
metered path). A local *code* model is a download decision for the owner
(≈1 GB for 1.5B, ≈5 GB for 8B) and it will not be as capable as the gateway.

## 5. The contract (unchanged, from `PIPELINE_DESIGN.md`)

* answer ≤ 512 tokens, **artifact on disk** (the Base tier cuts output at
  **1024** tokens — measured: 10 of 998 responses sat exactly there);
* the router's trust is a **receipt**: `cmd` + `exit` + `sha256` of the
  artifact, never prose;
* the gate and the verifier are **code**;
* the plan is **re-planned after each step**;
* per-run caps: **$0.15 / 60 requests** (our proxy now answers 429), plus the
  native `steps` cap per agent;
* the corpus keeps `no-op` and `block` classes as the pipeline's own negative
  controls (*own-check fault injection*).

## 6. Files proposed in `proposals/` (not applied to your config)

| file | purpose |
|---|---|
| `opencode.jsonc.fragment` | `subagent_depth: 2`, `small_model`, the two agent definitions, `permission.task` globs, the MCP server entry |
| `agent-local-executor.md` | sub-agent: local model, `steps: 4`, may spawn only `micro-*` |
| `agent-micro-worker.md` | micro-agent: local model, `steps: 2`, `hidden: true`, one file, receipt only |
| `mcp_pipeline_server.py` | the deterministic pipeline as one MCP tool (`pipeline_run`) |

Applying the fragment to your **global** config is your decision: it changes
the model of your daily driver, and the local model does not exist on this
machine yet.

## 7. Open decisions (owner)

1. **Executor:** gateway (recommended, measured cheap and strong) vs local
   1.5–3B (offline/privacy; download ≈1 GB; weak) vs local 8B (≈5 GB; slow on
   CPU).
2. **Topology:** B (MCP, recommended — the only one that realises 512–4096) vs
   A (OpenCode-native, simpler, but needs ≥16k local context).
3. **Build the MCP skeleton now?** (~200 lines, no model calls, testable
   offline against a fake executor.)
4. **The daily driver's model:** today `tirtha/auto` bills every thinking turn
   from the $59.25 credit; switching the global model to a free OpenCode-account
   model stops that.
