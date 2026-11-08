# Graceful Degradation

[English](GRACEFUL_DEGRADATION.md) · [Русский](../ru/GRACEFUL_DEGRADATION.md) · [中文](../zh/GRACEFUL_DEGRADATION.md)

> Version 3.5.0. What the code does when a component is missing. There is no
> numbered "degradation level" model in this codebase — only the fallbacks below.

## 1. Three outcomes

| Outcome | How you see it |
|---|---|
| **Full answer** | normal result |
| **Answer with holes** | result plus a `degraded: [...]` list (in `investigate`) or a warning line |
| **Failure** | JSON error envelope: `{"ok": false, "error": {"code", "message", "next_action", "details"}}`. `details` keeps the legacy `status` (`error`/`warning`/`timeout`), `detail`, `latency_ms`, `tool`, `recoverable` |

Rule: a *secondary* channel may fail silently (it must not take the answer down);
a *primary* capability fails loudly with a status the caller can branch on.

## 2. Retrieval ladder (default text-first configuration)

`MSCODEBASE_DENSE_OFF=true` and `MSCODEBASE_SQLITE_CHUNKS=true` are the defaults:

```
SQLite FTS5 / BM25 → optional graph bucket → on-demand cosine rerank (top-N)
                   → exact-name boost → dedupe
```

| Component missing | Behaviour | Where |
|---|---|---|
| Embedder | candidates still come from FTS5 + graph; the on-demand rerank raises, is caught, and the fused pool is returned unchanged | `engine.py::_apply_ondemand_reranker_async` |
| Reranker (BGE / multi-provider) | RRF ordering returned as-is; `is_available == False` short-circuits before any call | `engine.py::_apply_multi_reranker_async` |
| Graph DB | graph bucket yields nothing; text results unaffected | `_sqlite_hybrid_search_async` (graph stage wrapped in `try/except`) |
| SQLite chunk store (init failed) | warning logged, `_chunk_store = None`; the FTS5 tier is skipped and the call falls through to graph / BM25 (and dense, if enabled) | `Searcher.__init__`, `hybrid_search_async` |
| Reindex in progress | sync path returns **an empty result immediately** instead of blocking on DB locks; async path raises "retry in a few seconds" | `_reindex_fast_fail()`, `hybrid_search_async` |

An empty answer during a reindex is deliberate but looks like "no match", so
check `codebase(action="index", path="progress")` before concluding the query is
bad.

## 3. Legacy dense path (`dense_off=false`)

`fast` embeds the query; if the embedder throws, `query_vector` becomes `None`
and the call continues on FTS5 + graph (E24: an unguarded embed used to fail
10/10 while `quality` degraded). `quality` adds the reranker stage, skipped when
no provider answers. Dense retrieval is an enhancement, never a precondition.

## 4. `investigate` — per-channel degradation

Seven channels in two passes, per-channel timeouts (12 s, 15 s for grep; whole
tool 30 s). Pass 1: `search`, `symbols`, `grep`. Pass 2: `impact`, `graph`,
`tests`, `memory`. A timeout appends `name:timeout`; an exception appends
`name:<ExceptionType>`. The merged answer is still returned and ranked by
`(channel count, rank)`, but you always see which channels were silent:

```
🧭 investigate: `who calls ack_impact`
   identifiers: ack_impact
   results: 6 | degraded: tests:TimeoutError
```

### Evidence, not confidence

`grep` is the only channel that can say *this identifier occurs in this file*.
The other channels always answer with neighbours, so the header carries the exact
count per identifier — and says so when the subject itself occurs nowhere:

```
🧭 investigate: `where is build_call_graph defined`
   identifiers: build_call_graph, defined
   results: 8
   exact: build_call_graph=30, defined=20
```

```
🧭 investigate: `where is missing_widget implemented`
   identifiers: missing_widget, implemented
   results: 8
   ⚠️ exact: missing_widget=0, implemented=5 — the first identifier does not occur
   in the indexed code; the results below are neighbours, not matches.
```

Four rules that must stay true (guard: `tests/test_no_silent_success.py`):

1. an empty population is a refusal (`exit 2`, stderr reason), never a "0 %" line;
2. a channel that failed is named in `degraded`, and its silence never turns into
   "0 hits" — silence is not a measurement;
3. `latency_ms` comes from a clock: a 60 ms call reports at least 50, and two
   different costs produce two different numbers;
4. two non-exact channels naming the same place is correlation, not proof — the
   `exact:` line is not raised by agreement.

## 5. Tool-level failure and timeouts

`@error_boundary(name, timeout_ms=...)` is the single wrapper:

- the timeout is a real `asyncio.wait_for` — a hung coroutine is cancelled;
- **only timeouts retry** (1 s apart). `ToolError` is deterministic and returned
  immediately; an unexpected exception is logged with a traceback and returned as
  `INTERNAL_ERROR` with the message sanitised (absolute paths replaced, capped at
  200 chars);
- budgets: 30 s for `write` and `investigate`, 45 s for `get_health_report`,
  300 s for `dual_arm_health_check`;
- every call is recorded for `intel_tool_health` / `get_tool_metrics_summary`,
  failures included, so a channel that always fails is visible as a statistic.

### Error contract (breaking change, 2026-11-08)

Every failure returns JSON text, not a Markdown block:

```json
{"ok": false,
 "error": {"code": "INDEX_NOT_READY",
           "message": "Index is not ready",
           "next_action": "Index is empty or building. Call intel_trigger_reindex(mode='incremental') …",
           "details": {"status": "warning", "tool": "search_code",
                       "detail": "Run index_project_dir() to initialize",
                       "latency_ms": 12, "recoverable": true}}}
```

`code` is one of `VALIDATION_FAILED`, `NOT_FOUND`, `AUTH_REQUIRED`, `TIMEOUT`,
`RATE_LIMIT`, `INDEX_NOT_READY`, `REINDEX_IN_PROGRESS`, `DEPENDENCY_DOWN`,
`CONFLICT`, `INTERNAL_ERROR` (`src/core/error_envelope.py`). Branch on `code`;
read `next_action` instead of inventing a retry strategy. A dictionary result with
an error-like `status` (`error`, `warning`, `denied`, `too_large`,
`not_installed`) is converted to the same envelope — it can no longer be rendered
as a successful "✅ Completed" answer.

`isError` is `true` for these payloads: `src/mcp/error_results.py` wraps the
low-level CallTool handler once (installed by `create_mcp_server`) and flips the
flag when the result text is exactly the envelope, leaving the text
byte-identical — `json.loads(content[0].text)` still works. If a future `mcp`
release changes that private surface, `tests/test_mcp_is_error.py` fails and the
flag degrades to `false` with a log line, never to a mangled payload.

Inline and dev tools (`generate_docs`, `bump_version`, `auto_update_docs`,
`install_git_hooks`, `refresh_db_connection`) return the same envelope instead of
the old hand-written `Error: …` / `❌ …` strings, so they carry the flag too.

## 6. Indexing

- **Text-only (default)** — `index_project()` routes to
  `_index_text_only_project()`: parse, chunk, write to SQLite, update the graph.
  No embedder is contacted.
- **Dense (`dense_off=false`)** — the embedder is required. `is_ready()` false
  aborts with "Embedder not ready. Indexing aborted."; a provider returning the
  wrong number of vectors aborts the batch rather than writing a half-index.

A missing Tree-sitter grammar degrades one language, not the run: `parser.py`
imports each grammar in its own `try/except ImportError`.

## 7. Providers

`RemoteEmbedder.mode` ∈ `onnx`, `onnx_server`, `lm_studio`, `ollama`,
`llama_cpp`, `fallback`, `unknown`. Startup sets `fallback` when nothing answers
("safe default — don't pretend ONNX works"); a scanner re-checks with backoff
(30 s base, 300 s cap). llama.cpp embed does 3 batch retries with backoff, then
per-chunk retries, then raises — it does not invent zero vectors. Rerankers (LM
Studio, Ollama, llama.cpp, HTTP ONNX) are probed at init; all unreachable means
`is_available == False` and RRF ordering. The optional ONNX server is a
subprocess on `127.0.0.1:1235` (`DISABLE_ONNX_FALLBACK=true` removes it).

## 8. LSP and network

`lsp_*` tools need `basedpyright-langserver` on `PATH`. Without it each returns
"LSP недоступен (basedpyright не найден). …" and points at the symbol index; a
failed start is cached with a TTL and re-probed, so installing basedpyright later
does not need a permanent restart. The LSP→MCP bridge itself was removed on
2026-07-20 and no tool depends on it.

Nothing in the default path uses the network. Exceptions are opt-in: downloads in
`install.py` (always prompted) and the optional `tree-sitter-language-pack`, whose
extra parsers download on first use.

## 9. What does **not** degrade

"Graceful" here would mean "silently wrong":

| Situation | Response |
|---|---|
| Empty index (`total_chunks == 0`) | `IndexNotReadyError` → `🟡 Warning: Index is not ready`, not "no results" |
| Write to a load-bearing file without ack | `denied` from `modification_guard`, with an impact token |
| Ambiguous symbol for a write | `denied`, candidate list, no silent pick |
| Destructive action outside a trusted root | refusal per `trust_boundary` policy |
| `execute_script` when not enabled | tool not registered at all |
| Sandbox violation in `execute_script` | `SandboxViolation` before execution |

## 10. How to observe degradation

1. `get_health_report()` — index, providers, resources, memory warnings.
2. `codebase(action="index", path="status")` — `total_chunks`, files.
3. `get_runtime_counters()` — `verdict_blocked_*` reasons; `blocked > 5%` of
   checks is the documented signal to look at the architecture.
4. `intel_tool_health()` (full profile) — success rate, P50/P95, repeat rate.
5. `investigate` `degraded[]` — per-call channel failures.
6. `get_logs()` — recent warnings/errors; payloads stay in logs, not responses.

---

**Verified against:** `src/core/search/engine.py` (tier order, rerank fallbacks,
`_reindex_fast_fail`), `src/core/error_handler.py` (`error_boundary`, retry
policy, `_format_error_response`, `IndexNotReadyError`, message sanitising),
`src/mcp/tools/base.py` (`require_index` → `IndexNotReadyError`),
`src/mcp/tools/investigate_tool.py` (7 channels, timeouts, `degraded`),
`src/core/indexing/indexer.py` (`index_project` → text-only),
`src/core/indexing/index_project_runner.py` (abort on embedder failure),
`src/core/indexing/index_pipeline.py`, `src/core/indexing/parser.py`,
`src/providers/embedder/remote_embedder.py`,
`src/providers/reranker/multi_provider.py`,
`src/providers/reranker/llama_runner.py`, `src/mcp/tools/lsp_tools.py`,
`src/core/lsp_client.py`, `src/mcp/tools/system_tools.py`,
`src/core/runtime_coordinator.py`, `src/config/settings.py`,
`src/core/error_envelope.py`.
