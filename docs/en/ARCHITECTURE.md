<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[English](ARCHITECTURE.md) · [Русский](../ru/ARCHITECTURE.md) · [中文](../zh/ARCHITECTURE.md)

# MSCodeBase Intelligence — Architecture Guide

> **Current as of 2026-10-25.** This document describes the default Phase 3
> runtime: SQLite FTS5/BM25 plus PropertyGraph. Embeddings, reranking and the
> LanceDB vector path are optional and are called out explicitly.

---

## 1. Design goals

The server exists to give an AI assistant grounded, local answers about a
codebase without making a remote service or a large model mandatory.

1. **Local-first.** Core search, graph queries and project memory work without
   network calls.
2. **Deterministic before probabilistic.** Exact symbols, paths and BM25 are
   tried before optional semantic layers.
3. **Fail open, not silent.** Missing embedder, empty graph or stale index must
   produce a diagnosis, not a fabricated answer.
4. **One contract for humans and agents.** The same tool schema is used by the
   Zed agent, scripts and tests.
5. **Observable.** Runtime passport, index status, health report and logs are
   first-class tools, not debug afterthoughts.

## 2. Runtime at a glance

```text
Zed
 ├── built-in LSP (autocomplete, diagnostics)
 └── MCP client
      │
      ▼
 src/main.py (stdio) or src/remote_main.py (HTTP)
      │
      ▼
 server_factory.create_mcp_server()
      ├── create_service_collection()      DI container
      ├── register_all_tools()             64 registered tools
      └── notification / extension hooks
      │
      ├── Search        core/search
      ├── Index         core/indexing
      ├── Graph         core/graph.py + core/search/graph_adapter.py
      ├── Memory        core/intelligence
      ├── Writes        core/modification_guard.py + mcp/tools/write_tools.py
      └── Optional      providers/embedder, providers/reranker, LSP client
      │
      ▼
 Storage
      ├── <project>/.mscodebase/chunks.db       SQLite + FTS5
      ├── <data_root>/projects/<hash>/graph.db  PropertyGraph
      ├── <data_root>/projects/<hash>/intelligence/  memory, incidents
      └── <data_root>/logs/                     server logs
```

`<data_root>` is `%LOCALAPPDATA%/mscodebase` on Windows, or the platform
equivalent. Project artifacts live outside the repository; `chunks.db` is the
only store that remains inside the project directory.

## 3. Layers

| Layer | Responsibility | Main modules |
|---|---|---|
| Entry | Process start, project-root resolution, stdio/HTTP transport | `src/main.py`, `src/remote_main.py` |
| Protocol | MCP server, lifecycle, notification/extension hooks | `src/mcp/server.py`, `server_factory.py` |
| Tool | Thin adapters: validation, formatting, error boundary | `src/mcp/tools/*.py`, `server_tools.py` |
| Core | Search, indexing, graph, memory, write guards | `src/core/*` |
| Providers | Optional embedders, rerankers, LSP client | `src/providers/*`, `src/core/lsp_client.py` |
| Storage | SQLite/FTS5, PropertyGraph, JSON memory, logs | `chunk_store.py`, `graph.py`, `intelligence/` |

The tool layer never implements ranking or parsing itself. It resolves a
project-scoped service and delegates to core.

## 4. Entry points and lifecycle

- `src/main.py` starts the stdio MCP server used by the Zed extension. It
  resolves the extension/project root, configures logging and starts the
  server loop.
- `src/remote_main.py` exposes the same server over an authenticated HTTP
  transport for remote use. It is optional and off unless configured.
- `src/mcp/server_factory.py` creates the server, builds the DI container,
  registers tools, wires notifications and registers shutdown handlers.
- `src/mcp/server_tools.py` owns registration and the tool allowlist.

A second project in another Zed window is isolated by
`ProjectIndexerRegistry`: each project gets its own indexer/searcher/graph
handles, with an LRU bound and resource monitoring.

## 5. Dependency injection

`src/core/di_container.py` provides `ServiceCollection` and
`create_service_collection(project_root)`. Services are singletons scoped to the
server process:

- project root and parser;
- indexer/searcher and optional embedder;
- PropertyGraph and symbol index;
- `ProjectIndexerRegistry` / `MultiProjectSearcher`;
- rate limiter, circuit breaker and notification broker.

Tool classes receive the collection through constructor injection. They do not
construct indexers or open databases directly. Shutdown closes registered
resources and releases background tasks.

## 6. Tool layer

The server registers **64 tools**:

- 31 core tool classes (search, LSP, graph, analysis, write, lifecycle);
- 16 `intel_*` tools;
- 13 inline diagnostic tools;
- 4 dev tools.

`execute_script` is a 65th, optional tool and is registered only when
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`. The default allowlist exposes **49**
tools; `MSCODEBASE_MCP_TOOLS` controls visibility (an empty value shows all
registered tools).

`codebase(action=...)` is a hub over index, git and write operations. Search
has a dedicated `search_code` tool and a `plan_search` helper that returns a
deterministic plan (primary query, exact tokens, symbols, concepts, intent).

All tools are wrapped by `error_boundary`, which applies a timeout, records
telemetry and returns a structured error instead of hanging the MCP loop.

## 7. Indexing pipeline

```text
discover files
  → FileGuard (extensions, size, binaries, system dirs, .gitignore)
  → parser (Tree-sitter; language-specific extractors)
  → chunks + symbols + calls/imports/assignments/decorators/overrides
  → SQLiteChunkStore (text + FTS5) and PropertyGraph
```

Key rules:

- `experiments/**` is **excluded from the index**. It contains frozen panels and
  run artifacts; indexing them caused BM25 to return the panel itself instead of
  code. The files remain tracked in git.
- Incremental indexing updates a file's chunks and graph rows in one
  transaction.
- Full vector reindex is intentionally blocked when `MSCODEBASE_DENSE_OFF=true`.
  Use `scripts/reindex_text_only.py` for text chunks and
  `scripts/rebuild_graph.py` for a graph-only rebuild.
- A `build_head` marker is written only after a full successful index, so
  freshness can be checked against git HEAD.
- `FileGuard` and `SafePathManager` reject paths outside the project and system
  directories before parsing.

## 8. Storage

| Store | Path | Purpose |
|---|---|---|
| Chunk store | `<project>/.mscodebase/chunks.db` | Chunk text, metadata, FTS5 index |
| Graph | `<data_root>/projects/<hash>/graph.db` | Symbols, files and typed edges |
| Memory | `<data_root>/projects/<hash>/intelligence/` | Project memory, incidents, jobs |
| Logs | `<data_root>/logs/` | Server and tool diagnostics |

LanceDB is a legacy/optional vector store. It is not required by the default
text-first path and is not the primary source of candidates when
`MSCODEBASE_SQLITE_CHUNKS=true`.

## 9. Search integration

Search is the largest core subsystem. The default path is:

1. SQLite FTS5/BM25 candidates;
2. optional symbol/graph stage for identifier-shaped queries;
3. optional on-demand rerank;
4. exact-name boost and symbol deduplication;
5. docs routing at the tool level when the BM25 margin is strong.

The full RRF/MMR/anchor pipeline in `core/search/engine.py` belongs to the
optional dense/LanceDB path or to older code paths. It is not silently applied
to every Phase 3 query. See [SEARCH_PIPELINE.md](SEARCH_PIPELINE.md) for the
exact split.

## 10. Intelligence and memory

`core/intelligence/` implements project memory and incident handling:

- ADRs and known issues are stored as records with status and evidence;
- incidents can be logged, searched and predicted from runtime data;
- `verify-on-read` can mark memory facts as verified, refuted or superseded;
- retraction/supersede preserve history instead of deleting it.

Memory is local and project-scoped. It is not a general-purpose chat log.

## 11. Writes and safety

Write tools (`rename`, `move`, `safe_delete`, `replace`, `insert_before/after`)
operate on symbols, not raw text replacements. The pipeline is:

1. resolve the symbol and its references;
2. compute an impact summary;
3. require `ack_impact` when the file is load-bearing;
4. preview the change;
5. apply only with `apply=true`, then refresh chunks/graph.

Cross-file rename may use the basedpyright LSP client; on timeout it falls back
to the SymbolIndex. `execute_script` is disabled by default and, when enabled,
uses AST validation, an import wrapper and a subprocess sandbox.

## 12. Concurrency and multi-window behavior

- One indexer/searcher per project, resolved through the registry.
- SQLite writes are serialized by the chunk store lock; reads are safe across
  threads.
- Background indexing uses a watchdog heartbeat and job state, so the agent can
  poll instead of blocking the editor.
- External processes use `Popen` + `communicate(timeout=...)`, not
  `capture_output` in daemon threads, to avoid Windows pipe deadlocks.
- A reindex fast-fail returns a clear "index is rebuilding" error instead of
  hanging.

## 13. Failure modes and operational checks

| Symptom | First check | Fix |
|---|---|---|
| Graph tools return nothing | `graph.db` nodes/edges | `python scripts/rebuild_graph.py` |
| Search returns experiment docs | index contains `experiments/**` | reindex; FileGuard now excludes them |
| Docs always miss | gold is `docs/en`, result is `docs/ru` | normalize by basename |
| Index is stale | `codebase(action="index", path="status")` | `scripts/reindex_text_only.py` |
| Embedder missing | `debug_runtime_passport()` | text path still works; configure provider if needed |
| Tools missing from client | `MSCODEBASE_MCP_TOOLS` | add names or set empty for all |

## 14. Testing and verification

- `pytest tests/` — unit/integration suite; markers separate integration and
  benchmark tests.
- `python scripts/smoke_e2e.py --project .` — real embed/rerank/search, no
  mocks, when providers are available.
- `python scripts/rebuild_graph.py` and `python scripts/reindex_text_only.py`
  are the supported repair paths for graph/index drift.
- Search experiments live under `experiments/` with frozen inputs and raw runs;
  they are the source for the quality numbers in the README.

## 15. Related documents

- [SEARCH_PIPELINE.md](SEARCH_PIPELINE.md) — retrieval, ranking, modes and limits.
- [ARCHITECTURE_DEEP.md](ARCHITECTURE_DEEP.md) — historical deep dive and
  optional pipeline details.
- [GRACEFUL_DEGRADATION.md](GRACEFUL_DEGRADATION.md) — behavior when providers
  are unavailable.
- [INSTALL.md](INSTALL.md) — installation and repair commands.
- [README.md](../../README.md) — current public contract and measured quality.
