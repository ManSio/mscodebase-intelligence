# Executor: Gemma 4 26B A4B (QAT) on our own remote server (2026-10-21)

Own synthesis. Model facts are **Verified** against Google's blog, the model
card on Hugging Face, DeepMind's model page and the `models.dev` snapshot
OpenCode uses. Hardware facts about *this* machine are measured.

Owner's decision: the heavy model runs **on a remote server**; locally we keep
the orchestrator, the verifier and the filesystem, and the pipeline may run
**up to 2 concurrent worker streams**.

## 1. The model (verified)

| fact | value | source |
|---|---|---|
| architecture | MoE, 25.2 B total, **3.8 B active** per token, 30 layers, 8 active / 128 total experts + 1 shared, sliding window 1024 | HF model card, `google/gemma-4-26B-A4B-it-qat-q4_0-gguf` |
| context | **256 K** native (vocab 262 K, text+image) | model card |
| QAT release | 2026-06-05; formats: **Q4_0 GGUF** (llama.cpp/Ollama/LM Studio), **compressed-tensors w4a16** (vLLM/SGLang), unquantized, mobile wNa8o8 (E2B/E4B only) | Google blog "Gemma 4 with quantization-aware training" |
| QAT checkpoints | `google/gemma-4-26B-A4B-it-qat-q4_0-gguf` (and `-unquantized`, `-assistant` drafter) | HF collection `google/gemma-4-qat-q4-0` |
| **memory** | Q4_0 ≈ **14.4 GB** (Google's table); LM Studio: "minimum system memory 16 GB" | Google model docs; LM Studio |
| the trap | "the 4B-equivalent compute applies to **FLOPs, not to memory**" — all 26 B weights stay resident; a 16 GB card fits the weights but leaves ~1.5 GB for the KV cache | snackonai analysis, consistent with Google's table |
| quality | Arena text **1441** (#6 open model at release), MMMLU 82.6 %, MMMU Pro 73.8 %, AIME 2026 88.3 %, **LiveCodeBench v6 77.1 %**, GPQA-D 82.3 %, **τ²-bench (agentic tool use) 85.5 %** | DeepMind model page |
| license | **Apache 2.0** (commercially permissive) | Google blog |
| report | arXiv:2607.02770 | model card |
| availability in OpenCode | `gemma-4-26b-a4b-it` is present in the `models.dev` snapshot across many providers (context 128 k–256 k) | local `~/.cache/opencode/models.json` |

**The decisive number for us: τ²-bench 85.5 % (agentic tool use) and LiveCodeBench 77.1 %.** This is a *tool-calling* model, so it can be the executor of the microtask ladder — no need for a bigger model, and no need for the metered gateway.

## 2. What changes versus the Tīrtha-based plan

| aspect | Tīrtha (measured) | Gemma 4 26B A4B on our server |
|---|---|---|
| cost per request | ≈$0.0004 (Base) / up to $1.90–5.69 per 1M (escalated) | **electricity only** (own hardware) |
| rate limits / quotas | 100 free/month, then credit; Go-plan usage limits | none |
| silent model substitution | **yes** — `served_by` jumped between Cerebras / deepinfra / llama-sambanova | no: one model, one server |
| answer cap | **1024 output tokens** on Base (10 of 998 our answers sat exactly there) | our own `--max-tokens`; the truncation class disappears |
| context | 256 K native, but we declared 8 K | same, we declare 8 K/4 K/2 K |
| tool calling | works, but the 2026-10-18 plain-text bug existed (fixed their side) | our server, our prompt → no bracket-style leakage from OpenCode's examples (the actual root cause Tom found) |
| ops burden | none | we own the server, the model load, the KV cache, the concurrency |

⇒ The owner's principle becomes clean: **cloud model = thinking (orchestrator);
our own Gemma 4 = building.** Tīrtha is then optional (a fallback executor or a
second opinion), not the default.

## 3. Remote server spec — **LM Studio** (owner's decision)

LM Studio is the serving layer (0.4.0+), the model is Gemma 4 26B A4B QAT.

### 3.0 VERIFIED against the live server (2026-10-21: reads + one 147-token probe)

| fact | value |
|---|---|
| endpoint | `http://192.168.2.5:1234` — reachable: `/v1/models` and `/api/v1/models` both HTTP 200 |
| model id (**use exactly this string**) | `google/gemma-4-26b-a4b-qat` (from `GET /v1/models`; the HF-style id, not the short one) |
| quantization / context | publisher `google`, **Q4_0**, `max_context_length` **262 144** (native `/api/v1/models`) |
| also on the box | `gemma-4-26b-a4b-it-qat-mtp` (the **MTP drafter** for speculative decoding), `qwen/qwen3.6-35b-a3b` (262 k), `ernie-4.5-21b-a3b`, `mamba-codestral-7b`, `rwkv7-g1k-13.3b`, … |
| **tool calling through `/v1/chat/completions`** | **works**: the probe returned `tool_calls=[{"name":"write_file","arguments":"{\"content\":\"hello\",\"path\":\"src/x.py\"}"}]` |
| **cost of one worker turn** | **118 prompt + 29 completion = 147 tokens** (reasoning_tokens 0) |

**The number that decides the architecture:** a worker turn in a *minimal loop*
costs ≈150 tokens, where an OpenCode session's floor is **4 500–5 000** tokens
(measured on our own runs). That ~30× difference is why the 512–4 096 band is
reachable at all: brief (~300–500 tokens) + one tool schema (~120) + a
30–60-token receipt ≈ **500–700 tokens per step** ⇒ **5 microsteps ≈ 3–4 k
tokens** — the owner's "2–4 k per microstep" target, now backed by a
measurement instead of an estimate.

### 3.1 Server configuration

| item | requirement / fact | source |
|---|---|---|
| server | `lms server start` (or Developer tab → "Start server"); "either on `localhost` or **on the network**" ⇒ the remote box is just a host:port | LM Studio server docs |
| OpenAI-compatible base URL | `http://192.168.2.5:1234/v1` (default port 1234) | LM Studio OpenAI-compat docs |
| **which endpoint** | use `/v1/chat/completions` (custom tools ✅, **verified live**) — **not** `/api/v1/chat`, which does **not** support custom tools (❌) | LM Studio endpoint comparison + our probe |
| **2 streams** | "Max Concurrent Predictions" (`n_parallel`) with continuous batching, llama.cpp engine **v2.0.0+**; **Unified KV Cache is on by default** ⇒ parallel slots do **not** hard-partition the KV preallocation (no extra memory overhead) | LM Studio parallel-requests docs, 0.4.0 blog |
| memory | weights 14.4 GB (Q4_0) + KV; LM Studio lists "minimum system memory 16 GB" for this model (CPU-offload path); a 24 GB card is the comfortable target | Google model docs, LM Studio model page |
| **known traps (verified in the LM Studio tracker)** | #2061 `n_parallel` **ignored on JIT/API loads**; #1714 `n_parallel` **resets to 4** after a TTL-triggered reload; #2262 the UI badge reports 4 even when the engine has 1 slot | lmstudio-ai/lmstudio-bug-tracker |
| ⇒ operational rule | "standard settings" means `n_parallel = 4` by default; our client caps itself at 2 streams, but the server should still be loaded with an explicit `lms load --parallel 2`, and the **engine's own log** (`srv load_model: initializing, n_slots = 2`) plus `lms ps` must be checked — never the badge or the saved config | follows the catalogue's "assert the control's starting state" |

**This is the same class of bug we already hit twice today** (a control built
from the wrong state, a badge/UI that lies): the parallel setting must be
*asserted at the engine level*, not assumed from configuration.

### 3.2 What changes versus the Tīrtha-based plan


The owner allows **2 parallel worker streams**. Consequences for the design:

1. **Scheduler:** `max_parallel = 2` — the plan is executed in waves of two
   microtasks; independent microtasks of one wave run concurrently, dependent
   ones stay serial.
2. **Fan-out:** the catalogue's *LLM map-reduce* fan-out of ~10 children
   becomes **5 waves of 2** (or 10 sequential). Wall time ≈ 5 × step time
   instead of 1 × step time; the **token count is unchanged** — parallelism
   buys latency, not tokens. (Our own measurement: 0.936ⁿ compounding applies
   to *steps*, not to parallel branches; a failing branch does not poison the
   other one, which is the real win of sectioning.)
3. **Budget:** the cap is now a *server* cap, not a money cap: 2 streams ×
   ≤8 k context × ≤3 steps. Our per-run money guard stays in place for the
   metered path, but the Gemma path is bounded by VRAM and the step budget.
4. **Verification stays serial** (pytest in the worktree) — it is CPU-only and
   must not race with a writer on the same file.

## 5. Provider wiring (local → remote, LM Studio)

Our own config, one provider, two levels (thinking vs building):

```jsonc
{
  "provider": {
    "lmstudio-remote": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Gemma 4 26B A4B (LM Studio, our server)",
      "options": { "baseURL": "http://192.168.2.5:1234/v1", "apiKey": "{env:LMSTUDIO_KEY}" },
      "models": {
        "google/gemma-4-26b-a4b-qat": {
          "name": "Gemma 4 26B A4B QAT",
          "limit": { "context": 8192, "output": 2048 }
        }
      }
    }
  },
  "agent": {
    "local-executor": { "model": "lmstudio-remote/google/gemma-4-26b-a4b-qat", "steps": 4, "mode": "subagent" },
    "micro-worker":   { "model": "lmstudio-remote/google/gemma-4-26b-a4b-qat", "steps": 2, "mode": "subagent", "hidden": true }
  }
}
```

`limit.context: 8192` is the **declared** budget — OpenCode itself respects it
(it is the same key the llama.cpp provider documents), so the 8 k/4 k/2 k ladder
becomes a property of the configuration rather than a promise in a prompt.

## 6. Open items for the owner

1. **The server**: what GPU does the remote box have? (24 GB → 2 streams at
   8 k; 16 GB → 2 streams only at ≤4 k, or 1 stream at 8 k.)
2. **The endpoint**: llama.cpp or vLLM, and is the QAT GGUF / compressed-tensors
   checkpoint already downloaded?
3. **Orchestrator model**: which cloud model does the top level use? (Tīrtha's
   key is metered; an OpenCode-account model is free but rate-limited; a
   frontier model is the "thinking" tier the owner wants.)
4. **Tīrtha's role** after this: fallback executor, or dropped from the
   pipeline entirely (and the $5.90 we already spent stays the final bill)?
