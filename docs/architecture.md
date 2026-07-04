# MSCodeBase Intelligence — Architecture Guide

> **Version:** 2.2.0  
> **Last updated:** 2026-07-04  
> **Architecture:** Clean Architecture with DI Container

---

## Table of Contents

1. [Core Principles](#1-core-principles)
2. [Layer Architecture](#2-layer-architecture)
3. [DI Container (ServiceCollection)](#3-di-container)
4. [Tool Layer (37 class-based tools)](#4-tool-layer)
5. [Error Handling](#5-error-handling)
6. [Rate Limiting & Resilience](#6-rate-limiting--resilience)
7. [Data Flow: Request → Response](#7-data-flow)
8. [Windows Specifics](#8-windows-specifics)
9. [Testing Strategy](#9-testing-strategy)

---

## 1. Core Principles

```
┌──────────────────────────────────────────────────────────────────┐
│              Four Layers of Clean Architecture                    │
│                                                                  │
│  Layer 1: main.py / lsp_main.py  (Entry points, minimal)          │
│  Layer 2: mcp/server.py          (DI routing, tool registration)  │
│  Layer 3: mcp/tools/*.py         (37 class-based tools)           │
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

### 2.1 Entry Points

| File | Protocol | Purpose |
|------|----------|---------|
| `src/main.py` | MCP STDIO | AI-ассистент в Zed Chat |
| `src/lsp_main.py` | LSP STDIO | Индексация через didSave/didChange от Zed |

Both use the same `create_service_collection()` factory.

### 2.2 MCP Server

`src/mcp/server.py` — **~220 lines** (was 3,100 before refactoring).

Responsibilities:
1. Resolve project root (`resolve_project_root()`)
2. Create DI container (`create_service_collection()`)
3. Register 37 tools + 10 intel_* tools
4. Register system prompt (mscodebase-rules)

**No business logic lives here.** Every tool is an import from `mcp/tools/`.

### 2.3 Tool Layer

`src/mcp/tools/*.py` — **10 files, 37 tools.**

Every tool:
- Inherits from `MCPTool` (ABC)
- Receives dependencies via constructor (Constructor Injection)
- Has exactly one entry point: `async def execute(**kwargs) -> dict`
- Is decorated with `@error_boundary(tool_name, timeout_ms)`

```python
class SearchCodeTool(MCPTool):
    """search_code — семантический поиск по коду."""

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
        self.require_index()  # проверка готовности индекса
        # ... логика
```

### 2.4 Core Layer

`src/core/*.py` — **23 files of pure business logic.**

Key modules:

| Module | Purpose | Depends on |
|--------|---------|------------|
| `di_container.py` | DI Container (15 services) | — |
| `error_handler.py` | ToolError + error_boundary | — |
| `rate_limiter.py` | DebounceBatch + CircuitBreaker | — |
| `indexer.py` | LanceDB vector storage | embedder, file_guard, parser |
| `searcher.py` | Hybrid search (BM25 + Dense + RRF) | indexer, embedder |
| `symbol_index.py` | Call Graph (BFS, PageRank) | parser |
| `intelligence_layer.py` | 10 intel_* tools | indexer, searcher, symbol_index |
| `remote_embedder.py` | LM Studio / Ollama / ONNX | config |
| `parser.py` | Tree-sitter AST | — |
| `file_guard.py` | .gitignore + extension filter | config |

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
| 8 | LmStudioCircuitBreaker | singleton | `CircuitBreaker(name="lm_studio")` |
| 9 | Indexer | singleton | `Indexer(db_path, embedder, ...)` |
| 10 | Searcher | singleton | `Searcher(indexer, embedder)` |
| 11 | DebounceBatch | singleton | `DebounceBatch(callback=searcher.reindex)` |
| 12 | ProjectRegistry | singleton | `ProjectRegistry()` |
| 13 | MultiProjectSearcher | singleton | `MultiProjectSearcher(embedder, registry)` |

---

## 4. Tool Layer

### 4.1 Tool Registration

In `src/mcp/server.py`:

```python
def _register_all_tools(mcp, services):
    tool_classes = [
        SearchCodeTool, GetSymbolInfoTool,
        NotifyChangeTool, IndexProjectDirTool,
        GetBranchInfoTool, GetIndexStatusTool,
        # ... 37 total
    ]

    for tool_cls in tool_classes:
        instance = tool_cls(services)
        mcp.tool(name=instance.name)(instance.execute)
```

### 4.2 All 37 Tools by Group

| Group | File | Tools |
|-------|------|-------|
| **Search** (3) | `search_tools.py` | search_code, get_symbol_info, impact_analysis |
| **Indexing** (3) | `indexing_tools.py` | notify_change, index_project_dir, index_health |
| **Git** (3) | `git_tools.py` | get_branch_info, get_commit_history, get_file_history |
| **System** (9) | `system_tools.py` | get_index_status, get_index_progress, get_index_timeline, watcher_status, get_logs, get_health_report, predict_eta, run_health_check, read_live_file |
| **Analysis** (5) | `analysis_tools.py` | structural_search, get_repo_map, get_repo_rank, scan_changes, generate_chunk_summaries |
| **Graph** (4) | `graph_tools.py` | cross_repo_search, cross_project_deps, graph_query, get_related_files |
| **Investigation** (3) | `investigation_tools.py` | get_bug_correlation, get_hotspots, find_similar_bugs |
| **Lifecycle** (3) | `lifecycle_tools.py` | submit_background_task, get_task_status, verify_action |
| **Intelligence** (10) | `intelligence_layer.py` | intel_get_runtime_status, intel_get_job_status, intel_code_topology, intel_log_incident, intel_get_project_memory, intel_add_memory_node, intel_get_hotspots, intel_analyze_incident, intel_predict_root_cause, intel_trigger_reindex |

---

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
ToolError          # Базовый: status, message, detail, recoverable
├── IndexNotReadyError  # Индекс пуст (warning, recoverable)
└── RateLimitError      # Rate limit превышен (warning, recoverable)
```

---

## 6. Rate Limiting & Resilience

### 6.1 SlidingWindowRateLimiter

```python
limiter = SlidingWindowRateLimiter()  # asyncio.Lock для thread safety

ok = await limiter.acquire("notify_change", max_per_sec=10.0)
if not ok:
    raise RateLimitError(detail="Too many notify_change calls")
```

### 6.2 DebounceBatch

Replaces immediate `searcher.reindex()` on every file change:

```python
batch = DebounceBatch(callback=searcher.reindex, config=DebounceConfig(
    debounce_ms=500,    # 500ms после последнего события
    max_batch_size=100, # или при 100 файлах — немедленный сброс
    max_wait_ms=5000,   # защита от бесконечного debounce
))
await batch.add("file.py")  # BM25 перестроится через 500ms (или при 100 файлах)
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
        ├── searcher.search(query)
        │       │
        │       ▼
        │   core/searcher.py
        │       ├── BM25 search (in-memory TF-IDF)
        │       ├── Vector search (LanceDB + LM Studio)
        │       └── RRF fusion + reranking
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

## 8. Windows Specifics

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

## 9. Testing Strategy

```
tests/
├── test_error_handler.py     # 18 tests — ToolError, error_boundary
├── test_rate_limiter.py      # 21 tests — SlidingWindow, DebounceBatch, CircuitBreaker
├── test_di_container.py      # 13 tests — ServiceCollection, 15 services
├── test_parser.py            # 4 tests — Tree-sitter parsing
├── test_execution_contract.py# 10 tests — verify_action
├── test_task_queue.py        # 6 tests — background task queue
├── test_branch_aware_index.py# 8 tests — get_branch_info
├── test_symbol_index_call_graph.py  # 8 tests — call graph
├── ... (20 more test files)
```

**Total: 325 tests.**

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
| `python -c \"from src.mcp.server import create_mcp_server; mcp = create_mcp_server()\"` | Verify server loads |
