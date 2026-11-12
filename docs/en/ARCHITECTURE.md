# Architecture

> Rewritten 2026-11-08. Describes the default Phase 3 runtime (text-first:
> SQLite FTS5/BM25 + PropertyGraph). Vector/LanceDB, embeddings, reranker and
> LSP rename are optional layers and are marked as such.
> Numbers live in [FACTS.md](../FACTS.md); this page explains the shape, not the counts.
> Client setup: [CLIENTS.md](CLIENTS.md). Configuration: [CONFIGURATION.md](CONFIGURATION.md).
> Commit gates: [HOOKS_AND_GATES.md](HOOKS_AND_GATES.md).

## 1. Layers

```text
┌──────────────────────────────────────────────────────────────┐
│ Client: MCP host — OpenCode (primary) or Zed (stdio, JSON-RPC)│
├──────────────────────────────────────────────────────────────┤
│ Tool layer        src/mcp/tools/*                             │
│   investigate · search_code · grep_code · get_symbol_info     │
│   impact_analysis · graph_query · codebase hub · lifecycle    │
│   every tool is wrapped by @error_boundary (timeout + envelope)│
├──────────────────────────────────────────────────────────────┤
│ Intelligence      src/core/intelligence/*                     │
│   project memory · incidents · health · jobs · telemetry      │
├──────────────────────────────────────────────────────────────┤
│ Core services     src/core/search, src/core/indexing, graph   │
│   Searcher · SQLiteChunkStore · Indexer · PropertyGraph       │
├──────────────────────────────────────────────────────────────┤
│ Providers         src/providers/*   (optional)                │
│   llama.cpp/ONNX/LM Studio/Ollama embedders · BGE-M3 reranker │
└──────────────────────────────────────────────────────────────┘
```

Rules enforced by the architecture linter (`scripts/architecture_linter.py`)
and the layer-boundary gate:

- `core` never imports `mcp`; tools depend on core, not the reverse.
- `RuntimeCoordinator` decides readiness; tools do not second-guess it.
- Each tool is one file (or one class) with one responsibility; the `codebase`
  hub dispatches by `action` instead of growing more top-level tools.

## 2. Composition and lifecycle

`src/main.py` → `create_mcp_server()` (`src/mcp/server_factory.py`):

1. Build the DI container (`src/core/di_container.py`) with data paths from
   `src/core/artifact_paths.py`.
2. Register core tools, then intel, inline diagnostics and dev tools
   (`register_all_tools`).
3. Apply the **tool profile** (`_apply_tool_profile`): the full registry is
   built (all 69 tools), then everything outside `CORE_PROFILE` is removed from the
   client surface. Registration does not depend on the profile — that sentence was
   false until 2026-11-08, when a hard-coded default allowlist still cut registration
   to 56 names and `_apply_tool_profile` ran before the dev tools registered. The
   invariant is now pinned by `tests/test_tool_profile.py`
   (`test_core_profile_registers_full_registry_then_hides`).
4. Start the stdio transport; providers and the contradiction ledger start in
   the background so the handshake is never blocked.

Per-request lifecycle: `require_ready_project()` → tool body → `error_boundary`
wraps the result (timeout, telemetry, structured error). Search tools also
trigger a throttled freshness check (hot-reload) before querying.

## 3. Storage

| What | Where | Format |
|---|---|---|
| Text chunks + FTS5 index | `<project>/.mscodebase/chunks.db` | SQLite |
| Graph (symbols, edges, meta) | `<data_root>/projects/<hash>/graph.db` | SQLite (PropertyGraph) |
| Project memory, incidents, jobs | `<data_root>/projects/<hash>/intelligence/` | JSON |
| Commit memory | `<data_root>/projects/<hash>/commit_memory/` | JSON |
| Logs, telemetry | `<data_root>/logs/`, `<data_root>/projects/<hash>/telemetry/` | files |
| Vector table (optional) | `<data_root>/projects/<hash>/lancedb_v2/` | LanceDB |

`<data_root>` is `MSCODEBASE_DATA_DIR`, else `%LOCALAPPDATA%/mscodebase`
(Windows) or `~/.cache/mscodebase`. Nothing but `chunks.db` and `.mscodebase/`
lives inside the project, and both are gitignored.

## 4. Indexing

Two entry points, one pipeline:

- **Full text index** — `scripts/reindex_text_only.py`: walk (FileGuard
  excludes), parse with Tree-sitter, write chunks to SQLite and symbols/edges
  to the graph. No embeddings.
- **Incremental** — `FreshnessChecker` compares `(mtime, size, hash)` of files
  on disk with the SQLite store, reindexes changed/new files and prunes deleted
  ones. Runs throttled (default 30 s) after searches, and at startup via the
  auto-index task when the store is empty.

`experiments/**` is excluded from indexing by `SystemArtifacts`
(`src/core/indexing/file_guard.py`): frozen panels must not leak into
retrieval.

## 5. Search stack

`Searcher` (`src/core/search/engine.py`) owns retrieval:

- **Phase 3 path** — SQLite FTS5 candidates (limit × 4, capped), optional
  on-demand rerank of the top pool; no LanceDB access.
- **Identifier short-circuit** — identifier-shaped queries go straight to the
  graph stage for an exact location.
- **Docs routing** — one extra FTS query over `docs/**`; if the best docs score
  exceeds the best code score by `MSCODEBASE_DOCS_MARGIN` (4.0), docs win.
- **Legacy dense path** — only when `MSCODEBASE_DENSE_OFF=false` and a provider
  is available.

Details and stage budgets are in [SEARCH_PIPELINE.md](SEARCH_PIPELINE.md).

## 6. Tool layer

**69 registered** tools (36 core + 16 intel + 13 inline + 4 dev); the default
`core` profile exposes **17**. `execute_script` is an optional 70th tool behind
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`.

The visible set is one entry per intent: `investigate`, `search_code`,
`grep_code`, `get_symbol_info`, `impact_analysis`, `graph_query`, `codebase`,
`read_live_file`, `notify_change`, `get_health_report`,
`intel_get_project_memory`, `predict_change`, `tool_help`, plus the four dev
tools. `MSCODEBASE_MCP_PROFILE=full` exposes everything;
`MSCODEBASE_MCP_TOOLS` remains an explicit allowlist.

`investigate` is a two-pass fan-out: pass 1 runs search, symbols and grep in
parallel; pass 2 runs impact, callers, tests and project memory for what pass 1
found. Results merge by `(file, line)` and carry the set of channels that found
each item; a channel that times out appears in `degraded[]`.

`codebase(action=…)` is a hub: `index` (status/progress/health/timeline),
`git` (log/history/branch), and the write actions (rename/move/safe_delete/
replace/insert) with preview and impact guards.

## 7. Safety and failure behaviour

- Every tool has a timeout; a hung provider degrades the answer, it does not
  freeze the server.
- Search/write tools refuse to run on an empty index instead of returning "no
  results" (empty and broken must look different).
- Writes are previewed; destructive actions require the impact acknowledgement
  token.
- Subprocesses are spawned with `Popen(stdin=DEVNULL, stdout=PIPE,
  stderr=DEVNULL) + communicate`; `capture_output=True` deadlocks when the
  server's stdout is the JSON-RPC pipe (AGENTS.md §5.16).
- The contradiction ledger (startup, cached 6 h) verifies `✅` claims in
  `AGENT_DIARY.md` against the code; its own failures are reported, never
  silently ignored.

## 8. Optional layers

- **Embeddings/reranker:** llama.cpp GGUF, ONNX, LM Studio or Ollama; used by
  the on-demand rerank and the legacy dense path.
- **LSP:** basedpyright-backed references/definition/diagnostics, with a hard
  start budget and a 30 s failure cache.
- **Vector store:** LanceDB, only when dense retrieval is enabled.

None of them is required for the default text-first path.

## 9. Code references (audited 2026-11-12)

Every claim above resolves to a symbol, not to prose. Audit table:

| Claim in this page | Code |
|---|---|
| entry point builds the server, DI first | `src/main.py::main`, `src/mcp/server_factory.py::create_mcp_server` (line 156), `src/core/di_container.py` |
| artifact layout (`<data_root>/projects/<hash8>/…`) | `src/core/artifact_paths.py::get_data_root`, `::project_hash`, `::get_graph_db_path`, `::get_logs_dir` |
| text chunks in `<project>/.mscodebase/chunks.db` | `src/config/settings.py::SearchConfig.sqlite_chunks` (`MSCODEBASE_SQLITE_CHUNKS`) |
| `experiments/**` excluded from indexing | `src/core/indexing/file_guard.py` |
| retrieval owner | `src/core/search/engine.py::Searcher` |
| parsing / graph | `src/core/indexing/parser.py`, `src/core/graph.py` |
| profile `core` = 17 of 69 registered | `src/mcp/server_tools.py::CORE_PROFILE`; measured with `tools/list`: 17 (`core`) / 69 (`full`), 2026-11-12 |
| optional LSP layer | `src/mcp/tools/` `lsp_*` tools, failure cache 30 s (`src/config/settings.py::LSPConfig`) |

