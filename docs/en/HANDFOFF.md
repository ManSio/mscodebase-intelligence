<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

# MSCodeBase Intelligence — Architecture and Development Experience

[🇬🇧 English](HANDFOFF.md) • [🇷🇺 Русский](../ru/HANDFOFF.md) • [🇨🇳 中文](../zh/HANDFOFF.md)

> A document for developers joining the project.
> Describes key architectural decisions, Windows pitfalls,
> and investigation results, so you don't step on the same rake.

---

## 🎯 What Is This Project

**MSCodeBase Intelligence** — an MCP server for semantic code search in Zed IDE.
Runs fully locally: LanceDB (vector index) + ONNX E5-base INT8 (in-process embeddings) + llama.cpp GGUF (reranker only) + OpenVINO INT8 (optional).

**Key numbers:**
- 59 MCP tools (42 core + 14 intel + 3 diagnostic) — including `query_graph` (Cypher engine)
- 11 tool files, 18 services in the DI container
- Index: ~3000 chunks, ~170 files, ~1550 symbols
- **PropertyGraph**: SQLite graph (15 node types, 27 edge types) in `.codebase/graph.db`

---

## 🔑 The Main Discovery: Project Resolution on Windows

**Problem:** The MCP server needs to know which project is open in the Zed window.
`ZED_WORKTREE_ROOT` and `current_dir` **don't work** on Windows (Zed bug).
Each window starts its own MCP process, but environment variables aren't passed.

**Solution:** read Zed's SQLite database directly:

```python
# 1. Get active_workspace_id from scoped_kv_store
conn.execute("""
    SELECT value FROM scoped_kv_store 
    WHERE namespace = 'multi_workspace_state'
""")
# → {"active_workspace_id": 2, ...}

# 2. Get the path by ID
conn.execute("""
    SELECT paths FROM workspaces WHERE workspace_id = ?
""", (active_id,))
# → "D:\path\to\project"
```

**Where:** `src/mcp/server.py`, function `resolve_project_root()`, priority 0.
**Limitation:** if a project has multiple windows — MCP doesn't know which one is active.

→ **Full investigation:** [`ACTIVE_WORKSPACE_RESOLUTION.md`](investigations/ACTIVE_WORKSPACE_RESOLUTION.md)
  Covers: 6 tested Zed mechanisms, internal Rust APIs, SQLite schemas, 4 failed approaches.

---

## 🏗️ Key Architectural Decisions

| Decision | Motivation |
|----------|-----------|
| **DI container (ServiceCollection)** | 18 services, lazy resolution, per-project registry + PropertyGraph |
| **late-resolve active indexer** | If LSP hasn't written the bridge file yet — pick up the first live workspace |
| **Two-phase reindex** | `intel_trigger_reindex` → job_id → `intel_get_job_status` (anti-spam) |
| **asyncio.Lock for File IO** | Race protection for concurrent writes to memory JSON files |
| **ui_formatter** | Unified Markdown style for all 33 tools (no raw JSON) |

---

## 🔧 What's Broken and Won't Be Fixed

| Component | Reason | Status |
|-----------|--------|--------|
| **LSP server** (`lsp_main.py`) | Standalone LSP — Zed doesn't register custom LSP names. LSP _client_ for rename (`lsp_client.py`) works fine | **WONTFIX** (standalone only) |
| **auto-restart MCP** | No hook in Zed to restart a crashed context_server | **WONTFIX** |
| **`ZED_WORKTREE_ROOT`** | Not set on Windows (Zed bug #36019) | **Workaround via SQLite** |

→ **Full LSP investigation:** [`LSP_WONTFIX.md`](investigations/LSP_WONTFIX.md)
  Summary: Zed requires a Rust/WASM adapter for a custom LSP. `settings.json` cannot
  register a new language — only override the path for an existing one.
  8 approaches tested, all failed.

---

## 🐛 Fixed Bugs (to prevent regressions)

### 1. DebounceBatch deadlock

**File:** `src/core/rate_limiter.py`
**Symptom:** MCP hangs 5 seconds after a batch of `notify_change`.
**Cause:** `await` inside `threading.Lock` (not reentrant) — 100% deadlock.
**Fix:** separation: `should_flush` decision under lock, the `await` itself — after releasing the lock.

### 2. Self-indexing guard

MCP server sometimes indexed itself (extension sources, ~500MB).
**Fix:** `_is_self_index_path()` check in `base.py` — blocks ext_root
and the Zed installation directory, throws `ToolError`.

### 3. Race condition in Project Memory

Concurrent calls to `intel_log_incident` + `intel_add_memory_node` overwrote
JSON files. **Fix:** `asyncio.Lock` in `IntelligenceStore`.

---

## 🗄️ Where Things Are Stored

| Data | Path |
|------|------|
| Vector index | `<project>/.codebase_indices/lancedb_v2/` |
| Project memory (ADR, issues) | `<project>/.codebase_indices/intelligence/` |
| Logs | `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` |
| Zed's database | `%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite` |

---

## 📁 Key Files

| File | What it does |
|------|-------------|
| `src/mcp/server.py` | `resolve_project_root()`, registration of all 33 tools |
| `src/mcp/tools/base.py` | `MCPTool` (base class), `resolve_indexer_for_request()` |
| `src/core/di_container.py` | 15 services, `ProjectIndexerRegistry` |
| `src/core/intelligence_layer.py` | 14 intel tools, `ProjectIntelligenceLayer` |
| `src/core/indexer.py` | LanceDB, vectorization, indexing |
| `src/core/searcher.py` | BM25 + Dense + RRF hybrid search |
| `src/utils/ui_formatter.py` | Unified Markdown format for all tools |
| `src/core/error_handler.py` | `_format_success_response`, `error_boundary` |
| `src/core/rate_limiter.py` | DebounceBatch, SlidingWindowRateLimiter |

---

## ⚠️ Windows Pitfalls

1. **Restricted Mode** — press "Trust and Continue" when opening a project for the first time
2. **MCP restart** — only File → Quit (not `window: reload`, not kill)
3. **Git subprocess** — `GIT_ASKPASS=echo`, `CREATE_NO_WINDOW`, timeouts
4. **LanceDB on Windows** — mmap files aren't released until `_safe_close()` + `gc.collect()`
5. **Paths** — MCP: `src\core\file.py`, terminal: `src/core/file.py`

---

## 🔗 Related Documents

| Document | About |
|----------|-------|
| `INSTALL.md` | Installation for users |
| `ARCHITECTURE.md` | Full architecture (10 layers) |
| `ZED_WINDOWS_QUIRKS.md` | Windows specifics |
| `investigations/LSP_WONTFIX.md` | Why LSP doesn't work |
| `investigations/ACTIVE_WORKSPACE_RESOLUTION.md` | SQLite active_workspace |
| `../../AGENTS.md` | Rules for AI agent in Zed |
