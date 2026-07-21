<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](ARCHITECTURE.md) • [🇷🇺 Русский](../ru/ARCHITECTURE.md) • [🇨🇳 中文](../zh/ARCHITECTURE.md)

# MSCodeBase Intelligence — Architecture Guide

> **Version:** 3.3.9  
> **Last updated:** 2026-07-21  
> **Architecture:** 4-Layer Architecture + Graph-Native PropertyGraph Layer + Data Flow Layer (Entry Points → MCP Server/DI → Tool Classes → Core Business Logic → PropertyGraph → Data Flow) with Multi-Window Registry + DocSync

---

## Table of Contents

1. [Core Principles](#1-core-principles)
2. [Layer Architecture](#2-layer-architecture)
3. [DI Container (ServiceCollection)](#3-di-container)
4. [Tool Layer (18 core + 13 intel + 7 inline + 3 dev + 1 optional = 42 total)](#4-tool-layer)
5. [PropertyGraph Layer (v3.0)](#5-propertygraph-layer-v30)
6. [Cypher Query Engine (v3.0)](#6-cypher-query-engine-v30)
7. [Error Handling](#7-error-handling)
8. [Rate Limiting & Resilience](#8-rate-limiting--resilience)
9. [Data Flow: Request → Response](#9-data-flow)
10. [Windows Specifics](#10-windows-specifics)
11. [Multi-Window Registry (v2.3+)](#11-multi-window-registry-v23)
12. [Testing Strategy](#12-testing-strategy)

---

## 1. Core Principles

```
┌──────────────────────────────────────────────────────────────────┐
│              Four Layers of Architecture                          │
│                                                                  │
│  Layer 1: main.py / lsp_main.py  (Entry points, minimal)          │
│  Layer 2: mcp/server.py          (DI routing, tool registration)  │
│  Layer 3: mcp/tools/*.py         (18 core + 7 inline + 3 dev)│
│  Layer 4: core/*.py              (Pure business logic)            │
└──────────────────────────────────────────────────────────────────┘
```

**Key rules:**
- **Core layer has NO MCP imports.** It's pure Python with business logic.
- **Tool layer NEVER creates dependencies.** Everything comes from DI.
- **server.py ONLY registers** — no logic, no formatting, no try/except.
- **Dependencies flow downward:** Main ← Server ← Tools ← Core.

---

## 2. Layer Architecture

### 2.0 Ten-Layer Runtime Architecture (v2.4)

```
 Layer 0: Filesystem                  — what files exist on disk?
 Layer 1: SystemArtifacts             — is this a system path?
 Layer 2: Bridge (LSP→MCP)           — which project did LSP report?
 Layer 3: Registry (IndexerRegistry)  — which Indexer owns this project?
 Layer 4: StateMachine (ProjectState) — what state is the project in?
 Layer 5: RuntimeCoordinator          — can we execute this request?
 Layer 6: ProjectContext              — what does the project look like now?
 Layer 7: Passport                    — which process is running?
 Layer 8: Intel Layer                 — what to do with this information?
 Layer 9: MCP Tools / AI Agent        — answer to the user
```

**Data flow:**
```
Filesystem → SystemArtifacts → Bridge → Registry → StateMachine
                                                          ↓
MCP Tools ← Intel Layer ← ProjectContext ← RuntimeCoordinator
```

**Key rule:** Tool does NOT access Registry, Bridge or Passport directly.
Everything goes through `RuntimeCoordinator.can_execute()` + `ProjectContext.capture()`.

### 2.1 Entry Points

| File | Protocol | Purpose |
|------|----------|---------|
| `src/main.py` | MCP STDIO | AI assistant in Zed Chat |
| `src/lsp_main.py` *(deleted)* | LSP STDIO | Replaced by LSP client `src/core/lsp_client.py` |

Both use the same `create_service_collection()` factory.

### 2.2 MCP Server

| `src/mcp/server.py` | **~220 lines** (was 3,100 before refactoring).

Responsibilities:
1. Resolve project root (`resolve_project_root()`)
2. Create DI container (`create_service_collection()`)
3. Register 18 core + 13 intel + 7 inline + 3 dev + 1 optional = 42 total
4. Register system prompt (mscodebase-rules)

**No business logic lives here.** Every tool is an import from `mcp/tools/`.

### 2.3 Tool Layer

`src/mcp/tools/*.py` — **14 files: 18 core tools + 7 inline + 3 dev + 1 optional (Hub & Spoke: codebase + execute_script + 17 native).**

Every tool:
- Inherits from `MCPTool` (ABC)
- Receives dependencies via constructor (Constructor Injection)
- Has exactly one entry point: `async def execute(**kwargs) -> dict`
- Is decorated with `@error_boundary(tool_name, timeout_ms)`

```python
class SearchCodeTool(MCPTool):
    """search_code — semantic code search."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="search_code")
        self.searcher = services.resolve(Searcher)
        self.symbol_index = services.resolve(SymbolIndex)

    @error_boundary("search_code", timeout_ms=15000)
    async def execute(
        self,
        query: str,
        mode: str = "auto",
        limit: int = 6,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        self.require_index()  # check index readiness
        # ... search logic
```

### 2.4 Core Layer

`src/core/*.py` — **30 files of pure business logic.**

Key modules:

| Module | Path | Purpose |
|--------|------|---------|
| `di_container.py` | `src/core/di_container.py` | DI Container (15+ services) |
| `error_handler.py` | `src/core/error_handler.py` | ToolError + error_boundary |
| `rate_limiter.py` | `src/core/rate_limiter.py` | DebounceBatch + CircuitBreaker |
| `engine.py` | `src/core/search/engine.py` | Hybrid search (BM25 + Dense + FTS5 + RRF) |
| `graph.py` | `src/core/graph.py` | PropertyGraph — SQLite property graph |
| `graph_adapter.py` | `src/core/search/graph_adapter.py` | SymbolIndexAdapter wrapping PropertyGraph |
| `cypher_engine.py` | `src/core/search/cypher_engine.py` | Cypher→SQL engine for PropertyGraph |
| `indexer.py` | `src/core/indexing/indexer.py` | LanceDB vector storage + indexing pipeline |
| `symbol_index.py` | `src/core/indexing/symbol_index.py` | Call Graph (BFS, PageRank) |
| `parser.py` | `src/core/indexing/parser.py` | Tree-sitter AST parser (16 languages) |
| `file_guard.py` | `src/core/indexing/file_guard.py` | .gitignore + extension filter |
| `db_manager.py` | `src/core/indexing/db_manager.py` | LanceDB table lifecycle (PID-lock, reindex guard) |
| `fts5_mixin.py` | `src/core/search/fts5_mixin.py` | FTS5 full-text search mixin |
| `scoring.py` | `src/core/search/scoring.py` | RRF + MMR diversity scoring |
| `layer.py` | `src/core/intelligence/layer.py` | Intel Layer (13 intel_* tools) |
| `runtime_coordinator.py` | `src/core/runtime_coordinator.py` | ExecutionVerdict + can_execute() |
| `project_context.py` | `src/core/intelligence/project_context.py` | Project state snapshot |
| `llama_runner.py` | `src/providers/reranker/llama_runner.py` | Lifecycle for llama-server.exe (reranker) |
| `remote_embedder.py` | `src/providers/embedder/remote_embedder.py` | ONNX E5-small INT8 embedder + LM Studio/Ollama fallback |
| `doc_sync_engine.py` | `src/core/doc_sync_engine.py` | Auto-sync docs with code (rename hook) |

### 2.5 Search Engine (v3.3)

```
┌─────────────────────────────────────────────────────────┐
│   Search Pipeline (engine.py)                            │
│                                                          │
│   query_str → embed() → BM25 → FTS5 → 3-way RRF → MMR  │
│                        ↕                                │
│   MultiSignalScorer: api_signature, graph_diffusion,     │
│   module_proximity, cochange_boost                       │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│   PropertyGraph (graph.py)                               │
│   SQLite (WAL + mmap), nodes/edges, JSON properties      │
│   — 15 node labels (File, Function, Class, Variable...)  │
│   — 27 edge types (CALLS, DEFINES, ASSIGNED_FROM, ...)  │
│   — Cypher query engine (MATCH→SQL)                     │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│   Data Flow Layer (v3.2.0)                               │
│                                                          │
│   1. Unified Walker — one Tree-sitter parse → calls +    │
│      assignments. Parse cache with content hash.         │
│   2. Conditional Flow — ASSIGNED_FROM edges have         │
│      condition_path (if/for/while/try/except)            │
│   3. Intra-procedural only — within function bodies      │
│   4. 16 languages: Python, Rust, TS, TSX, Go, JS,       │
│      Java, C#, Ruby, PHP, Kotlin, Swift, C, C++,        │
│      Scala, Dart                                        │
└─────────────────────────────────────────────────────────┘
```

### 2.6 Embedder: E5-small ONNX (in-process)

The MCP server now uses multilingual-e5-small via ONNX Runtime (CPU, in-process) as its primary embedder:

- **Model**: `intfloat/multilingual-e5-small` (384-dim)
- **Runtime**: ONNX (CPU, no GPU required)
- **Architecture**: in-process — no external HTTP server
- **Performance**: ~37 ch/s (was 18 i/s with BGE-M3)
- **RAM**: ~265 MB (was 285 MB + VRAM)
- **Config**: `EMBEDDING_DIMENSION=384`, `EMBEDDING_PROVIDER=e5_onnx`

The reranker still runs via llama-server (1 process, not 2).

Legacy fallback providers (LM Studio, Ollama, remote ONNX) remain available via `remote_embedder.py` for custom setups.

---

## 3. DI Container

### 3.1 ServiceCollection

```python
# src/core/di_container.py

services = ServiceCollection()

# Registering a singleton:
services.add_singleton(Indexer, indexer_instance)

# Registering a lazy factory:
services.add_factory(Searcher, lambda s: Searcher(s.resolve(Indexer), ...))

# Resolving:
indexer = services.resolve(Indexer)  # same instance every time
```

### 3.2 Registered Services (15)

| # | Service | Type | Created By |
|---|---------|------|------------|
| 1 | Path (project_root) | singleton | explicit |
| 2 | Path (db_path) | singleton | `_generate_unique_db_path()` |
| 3 | CodeParser | singleton | `CodeParser()` |
| 4 | FileGuard | singleton | `FileGuard(project_root)` |
| 5 | RemoteEmbedder | singleton | `RemoteEmbedder()` |
| 6 | SymbolIndex | singleton | `SymbolIndex()` |
| 7 | SlidingWindowRateLimiter | singleton | `SlidingWindowRateLimiter()` |
| 8 | CircuitBreaker | singleton | `CircuitBreaker(name="lm_studio")` |
| 9 | ProjectRegistry | singleton | `ProjectRegistry()` |
| 10 | MultiProjectSearcher | singleton | `MultiProjectSearcher(embedder, registry)` |
| 11 | ResourceMonitor | singleton | `get_global_resource_monitor()` |
| 12 | ResourceMonitorKey | singleton | `ResourceMonitor` (shared) |
| 13 | ProjectIndexerRegistry | singleton | `ProjectIndexerRegistry(max_cached=5)` |
| 14 | NotificationBroker | singleton | `NotificationBroker()` |
| 15 | IndexerFactoryKey | factory | `_create_indexer_for_path` |

---

## 4. Tool Layer

### 4.1 Tool Registration

In `src/mcp/server_tools.py`:

```python
def register_all_tools(mcp, services):
    tool_classes = [
        # Search (3)
        SearchCodeTool, GetSymbolInfoTool, ImpactAnalysisTool,
        # Hub: codebase (write/index/git/notify — multiplexed by action)
        CodebaseTool,
        # Spoke: E2B sandbox
        ExecuteScriptTool,
        # Analysis (5)
        StructuralSearchTool, GetRepoMapTool, GetRepoRankTool,
        ScanChangesTool, GenerateChunkSummariesTool,
        # Graph (3 — Phase 2: graph_query multiplexes cypher + related + flow)
        CrossRepoSearchTool, CrossProjectDepsTool, GraphQueryTool,
        # Investigation (3)
        GetBugCorrelationTool, GetHotspotsTool, FindSimilarBugsTool,
        # Lifecycle (3)
        SubmitBackgroundTaskTool, GetTaskStatusTool, VerifyActionTool,
    ]
    # +13 intel_* tools + 7 inline diagnostic + 3 dev + 1 optional
    # Total: 42 registered (18 core + 13 intel + 7 inline + 3 dev + 1 optional)
```

**Tool visibility filter:** By default ~16 tools visible. Set `MSCODEBASE_MCP_TOOLS=""` to show all 42.

### 4.2 All Tools by Group

| Group | File | Tools |
|-------|------|-------|
| **Search** (3) | `search_tools.py` | search_code, get_symbol_info, impact_analysis |
| **Hub: codebase** (1) | `codebase_tool.py` | codebase(action=rename/move/delete/replace/insert/notify/index/git) |
| **Spoke: E2B** (1) | `codebase_tool.py` | execute_script(code) |
| **Analysis** (5) | `analysis_tools.py` | structural_search, get_repo_map, get_repo_rank, scan_changes, generate_chunk_summaries |
| **Graph** (3) | `graph_tools.py` | cross_repo_search, cross_project_deps, graph_query |
| **Investigation** (3) | `investigation_tools.py` | get_bug_correlation, get_hotspots, find_similar_bugs |
| **Lifecycle** (3) | `lifecycle_tools.py` | submit_background_task, get_task_status, verify_action |
| **Write** (1) | `write_tools.py` | codebase(action={rename,move,delete,replace,insert,impact}) |
| **Indexing** (1) | `indexing_tools.py` | get_index_status, notify_change, watcher_status |
| **Git** (1) | `git_tools.py` | git(action={log,history,branch}) |
| **Docs** (1) | `doc_tools.py` | generate_docs, bump_version, auto_update_docs, install_git_hooks |
| **Meta** (1) | `meta_tools.py` | get_index_status, get_index_progress, get_index_timeline, get_health_report, get_logs |
| **System** (1) | `system_tools.py` | read_live_file, get_health_report, get_logs |
| **Intelligence** (13) | `intelligence/layer.py` | intel_get_runtime_status, intel_get_job_status, intel_code_topology, intel_log_incident, intel_get_project_memory, intel_add_memory_node, intel_get_hotspots, intel_analyze_incident, intel_predict_root_cause, intel_trigger_reindex, intel_get_project_context, intel_explain_project_state, intel_get_telemetry, intel_tool_health |
| **Diagnostic inline** (7) | `server_tools.py` | debug_runtime_passport, get_runtime_counters, intel_execution_timeline, get_health_report, get_logs, read_live_file, stale_detector |

> **Total:** 42 registered (18 core + 13 intel + 7 inline + 3 dev + 1 optional). Default visible: ~16. Show all: `MSCODEBASE_MCP_TOOLS=""`.

## 5. Error Handling

### 5.1 error_boundary Decorator

Every tool is wrapped with `@error_boundary`:

```python
@error_boundary("tool_name", timeout_ms=15000, max_retries=1)
async def execute(self, **kwargs) -> dict:
    ...
```

It guarantees:
1. **Real timeout** via `asyncio.wait_for(timeout_ms / 1000.0)`
2. **Unified JSON** always: `{"status": "ok"|"error"|"timeout"|"warning", "message": "...", "detail": "...", "latency_ms": 123}`
3. **Controlled errors** (`ToolError`) → return as-is without retry
4. **Unexpected errors** → logged with full traceback, returned as `"status": "error"`
5. **Timeout retry** — configurable via `max_retries`

### 5.2 ToolError Hierarchy

```python
ToolError          # Base: status, message, detail, recoverable
├── IndexNotReadyError  # Index empty (warning, recoverable)
└── RateLimitError      # Rate limit exceeded (warning, recoverable)
```

---

## 6. Rate Limiting & Resilience

### 6.1 SlidingWindowRateLimiter

```python
limiter = SlidingWindowRateLimiter()  # asyncio.Lock for thread safety

ok = await limiter.acquire("notify_change", max_per_sec=10.0)
if not ok:
    raise RateLimitError(detail="Too many notify_change calls")
```

### 6.2 DebounceBatch

Replaces immediate `searcher.reindex()` on every file change:

```python
batch = DebounceBatch(callback=searcher.reindex, config=DebounceConfig(
    debounce_ms=500,    # 500ms after last event
    max_batch_size=100, # or flush immediately at 100 files
    max_wait_ms=5000,   # prevent infinite debounce
))
await batch.add("file.py")  # BM25 rebuilds after 500ms (or at 100 files)
```

### 6.3 CircuitBreaker

```python
cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="lm_studio")

result = await cb.call(
    lambda: embedder.embed_batch(texts),
    fallback={"status": "fallback", "message": "LM Studio unavailable"}
)
# States: CLOSED → OPEN (5 failures) → HALF_OPEN (30s later) → CLOSED (success)
```

---

## 7. Data Flow

```
Zed AI Agent
    │
    ▼
MCP Tool Call (e.g., search_code("find indexer"))
    │
    ▼
error_boundary decorator
    ├── timeout check (asyncio.wait_for)
    ├── rate limit check (SlidingWindowRateLimiter)
    └── tool execution
            │
            ▼
    MCPTool.execute(**kwargs)
        │
        ├── self.require_index()  → IndexNotReadyError if empty
        ├── services.resolve(Searcher)
        ├── engine.hybrid_search(query)
        │       │
        │       ▼
        │   core/search/engine.py
        │       ├── BM25 search (in-memory TF-IDF)
        │       ├── Vector search (LanceDB + ONNX E5-small, in-process)
        │       ├── FTS5 search (SQLite FTS5, trigram+porter)
        │       └── 3-way RRF fusion + MMR diversity
        │
        └── return {"status": "ok", "results": [...]}
                │
                ▼
        error_boundary → {"status": "ok", ...latency_ms}
                │
                ▼
        Zed Chat (formatted JSON response)
```

---

## 8. Metadata Enrichment (v2.4.4+)

### 8.1 Chunk Metadata

Each chunk in LanceDB stores 6 metadata fields for deterministic
filtering and multi-granularity retrieval:

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `layer` | string | `"core"` | Architecture layer: core/mcp/utils/tests/... |
| `module_name` | string | `"core.parser"` | Logical module name from file path |
| `hierarchy_level` | string | `"method"` | Level: function/method/class/impl/lines |
| `is_public` | bool | `true` | Public/private (`_`-prefixed) |
| `symbol_type` | string | `"method_definition"` | AST node type |
| `parent_id` | string | md5 hash | Deterministic parent hash |

Layer detection — automatic, by file path:

| Path | layer |
|------|-------|
| `src/core/*` | `core` |
| `src/mcp/tools/*` | `mcp_tools` |
| `src/mcp/*` | `mcp` |
| `src/utils/*` | `utils` |
| `tests/*` | `tests` |
| `docs/*` | `docs` |
| `.agents/*` | `agents` |
| `scripts/*` | `scripts` |
| `.github/*` | `ci` |
| other | `root` |

### 8.2 Flat Tree Hierarchy (SproutRAG-style)

`parent_id` — deterministic md5 hash:

- **For method:** `md5(file_path + "::" + class_name)` — parent = class
- **For function:** `md5(file_path)` — parent = module
- **For giant function part:** `md5(file_path + "::" + symbol_name)` — parent = function

Enables multi-granularity retrieval without graph DB:
- Find all methods of a class → `get_chunks_by_parent_id("md5_hash")`
- Navigate up to module → aggregation by parent_id

### 8.3 Layer Filtering in search_code

    ```python
    # Only core layer
    search_code(query="DI container", filter_layer="core")

    # Only tests
    search_code(query="test_parser", filter_layer="tests")

    # No filter (all layers, as before)
    search_code(query="parser")
    ```

    Layer filtering works at the LanceDB level via `.where(prefilter=True)` — vector search only searches chunks of the specified layer. BM25 post-filters by layer from metadata.

    ---

    ## 9. Windows Specifics

### 8.1 Path Resolution

`PROJECT_PATH` may contain `$ZED_WORKTREE_ROOT` literal string (env var not resolved by Zed on Windows).
Solution: `resolve_project_root()` checks 7 fallback strategies:

1. Provided argument
2. LSP→MCP bridge (temp file from LSP, which knows `root_uri`)
3. `PROJECT_PATH` env var (resolved if not `$ZED`)
4. `ext_root` if it's a git repo
5. `ZED_WORKTREE_ROOT` env var
6. CWD (from Zed `settings.json`)
7. `ext_root` as final fallback

### 8.2 Git Subprocess Safety

```python
env["GIT_TERMINAL_PROMPT"] = "0"    # No interactive prompts
env["GIT_ASKPASS"] = "echo"         # No credential helper
env["GIT_PAGER"] = "cat"            # No pager
creationflags = subprocess.CREATE_NO_WINDOW  # No console window
```

### 8.3 Long Path Support

SafePathManager uses `to_win_long_path()` (prepending `\\?\`) for paths > 260 chars.

---

## 9. Multi-Window Registry (v2.3+)

v2.3+ supports **multiple open projects in Zed simultaneously**.
Previously DI held a singleton `Indexer` — when switching windows, state would break
(one `file_guard`, one `db_path`, shared `SymbolIndex`).

### 9.1 `ProjectIndexerRegistry`

`src/core/indexing/project_indexer_registry.py` — thread-safe registry of `Indexer` objects:

```python
registry = ProjectIndexerRegistry(
    max_cached=5,                      # LRU limit (5 projects = 1-2.5GB RAM)
    resource_monitor=get_global_resource_monitor(),  # adaptive throttling
)

# Per-project lazy creation via factory:
def _create_indexer(p: Path) -> Indexer:
    return Indexer(
        db_path=_generate_unique_db_path(p),
        file_guard=FileGuard(p),
        symbol_index=SymbolIndex(),  # isolated
        project_path=p, ...
    )

services.add_singleton(IndexerFactoryKey, _create_indexer)
indexer = registry.get_indexer(project_path, factory=_create_indexer)
```

**Guarantees:**
- **Isolation:** each window gets its own `FileGuard`/`SymbolIndex`/`db_path`.
- **LRU:** when the 6th project opens, the oldest `Indexer` is evicted.
- **Pressure-evict:** when RAM > 1GB or CPU > 85% — forced evict
  **before** creating a new `Indexer` (prevents OOM).
- **Cleanup:** `_safe_close()` resets LanceDB connection + `gc.collect()`
  (for Windows mmap handles).

### 9.2 `ResourceMonitor`

`src/core/indexing/resource_monitor.py` — stdlib-only monitoring (no `psutil`):

| Platform | Method |
|-----------|-------|
| POSIX | `resource.getrusage(RUSAGE_SELF).ru_maxrss` |
| Windows | `psapi.GetProcessMemoryInfo` via `ctypes` |
| CPU | `resource.getrusage` utime+stime delta / wall-clock |

**Thresholds:**
- Soft: 768MB / 75% CPU → throttle indexing (0.1s delay between files)
- Hard: 1024MB / 85% CPU → pressure-evict + 0.5-2s delay

```python
monitor = get_global_resource_monitor()
snap = monitor.sample()  # ResourceSnapshot (rss_mb, cpu_percent, threads)

if monitor.is_under_pressure():
    delay = monitor.suggest_throttle_delay_sec()
    time.sleep(delay)  # in Indexer.index_project between files
```

### 9.3 LSP per-workspace DI

`src/lsp_main.py` stores **per-workspace** DI containers:

```python
_services_per_workspace: dict[str, ServiceCollection] = {}

@server.feature("initialize")
async def on_initialize(ls, params):
    project_root = Path(urlparse(params.root_uri).path)
    ls._workspace_uri = params.root_uri
    ls._project_root = project_root
    init_components(project_root, workspace_uri=params.root_uri)
    # → creates isolated DI container for a WINDOW
```

LSP handlers (`did_open`/`did_change`/`did_save`/`did_close`/
`didChangeWatchedFiles`) receive `ls._workspace_uri` and resolve the correct `Indexer` via registry.

### 9.4 MCP `resolve_indexer_for_request`

`src/mcp/tools/base.py` — single entry point for per-project Indexer:

```python
def resolve_indexer_for_request(services, explicit_project_root=None):
    target = explicit_project_root or resolve_project_root() or DI_default
    registry = services.resolve(ProjectIndexerRegistry)
    factory = services.resolve(IndexerFactoryKey)
    return registry.get_indexer(target, factory=factory)

class MCPTool:
    def resolve_indexer(self, project_root=None):
        return resolve_indexer_for_request(self._services, project_root)
```

**All MCP tools** must use `self.resolve_indexer(...)`
instead of `self._services.resolve(Indexer)` — the latter no longer works
(Indexer is not a singleton).

### 9.5 HealthReport `_check_resources`

`src/core/code_health.py` — added method:

```python
def _check_resources(self):
    summary = get_global_resource_monitor().get_summary()
    self.metrics["process_rss_mb"] = summary["rss_mb"]
    self.metrics["process_cpu_percent"] = summary["cpu_percent"]
    self.metrics["registry_cached_projects"] = ...
    self.metrics["registry_evictions"] = ...
    if summary["under_hard_pressure"]:
        self.issues.append({...})
```

---

## 10. Testing Strategy

```
tests/
├── test_error_handler.py     # 18 tests — ToolError, error_boundary
├── test_rate_limiter.py      # 21 tests — SlidingWindow, DebounceBatch, CircuitBreaker
├── test_di_container.py      # 13 tests — ServiceCollection, 15 services
├── test_resource_monitor.py  # 11 tests — ResourceMonitor + ProjectIndexerRegistry (v2.3+)
├── test_parser.py            # 4 tests — Tree-sitter parsing
├── test_execution_contract.py# 10 tests — verify_action
├── test_task_queue.py        # 6 tests — background task queue
├── test_branch_aware_index.py# 8 tests — get_branch_info
├── test_symbol_index_call_graph.py  # 8 tests — call graph
├── ... (20 more test files)
```

**Total: 396 tests.**

Run:
```bash
pytest tests/ -m "not integration and not benchmark"
```

---

## Quick Reference

| Command | Description |
|---------|-------------|
| `python -m src.main` | Run MCP server (STDIO) |
| `pytest tests/` | Run all tests |
| `pytest tests/test_di_container.py -v` | Run DI container tests only |
| `python -c "from src.mcp.server import create_mcp_server; mcp = create_mcp_server()"` | Verify server loads |

---

## 11. Architectural Invariants

These rules must NOT be violated by any new PR.

```
1. Tool does not access Registry directly.
2. Tool does not read Bridge directly.
3. Tool works only through RuntimeCoordinator.
4. RuntimeCoordinator does not know about Search / Indexer / Memory.
5. ProjectContext is an immutable snapshot (does not start operations).
6. All system files are defined only through SystemArtifacts.
7. The indexer never indexes system artifacts.
8. Any project path goes through the single resolver (resolve_project_root).
9. All Intel tools use ProjectContext (not low-level APIs).
10. Any new runtime component must have a single responsibility.
11. Core layer has no MCP imports.
12. Tools do not create dependencies — everything through DI.
13. server.py registers — does not contain business logic.
```

**Code review check:** every PR must answer the question
"Which existing layer does this extend?". If the answer is "none, I created
a new Manager/Services/Provider" — this is a reason to stop and reconsider.
