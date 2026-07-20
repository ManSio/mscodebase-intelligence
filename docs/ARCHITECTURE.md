# MSCodeBase Intelligence — Architecture Documentation

## Overview

MSCodeBase Intelligence is a hybrid code intelligence system combining:
- **LanceDB** for vector storage and semantic search
- **ONNX Runtime** (CPU) for local embeddings (multilingual-e5-small-int8)
- **llama.cpp** for local reranking (BGE-M3)
- **FTS5** (SQLite) for full-text search
- **Tree-sitter / Python AST** for code parsing
- **MCP (Model Context Protocol)** for Zed IDE integration

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ZED IDE (Extension Host)                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    MCP Server (src/mcp/server.py)                 │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │ Intel Layer │  │ Core Tools  │  │ Inline/Diag │  39 tools     │  │
│  │  │  (12 tools) │  │  (19 tools) │  │  (8 tools)  │               │  │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘               │  │
│  └─────────┼────────────────┼────────────────┼──────────────────────┘  │
│            │                │                │                         │
│            ▼                ▼                ▼                         │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │              ProjectIntelligenceLayer (src/core/intelligence)   │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │  │
│  │  │ RuntimeCoord │  │ IncidentIntel│  │ ProjectMemory│           │  │
│  │  │  (can_exec)  │  │  (log/analyze)│  │  (ADR/tech)  │           │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘           │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      CORE SERVICES (src/core)                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │   Indexer    │  │   Searcher   │  │  SymbolIndex │  │  Embedder  │  │
│  │ (LanceDB +   │  │ (BM25+Dense+ │  │  (Property   │  │  (ONNX     │  │
│  │  FTS5 sync)  │  │   FTS5+RRF)  │  │   Graph)     │  │  CPU)      │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      EXTERNAL PROCESSES                                 │
│  ┌─────────────────────┐  ┌─────────────────────┐                      │
│  │ llama-server.exe    │  │  LanceDB (embedded) │                      │
│  │ (BGE-M3 reranker)   │  │  .codebase_indices/ │                      │
│  │ port 8081           │  │  lancedb_v2/        │                      │
│  └─────────────────────┘  └─────────────────────┘                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Two-Process Architecture (Critical)

**MCP runs as TWO linked processes** (parent-child):

| Process | Executable | Memory | Role |
|---------|------------|--------|------|
| **Launcher** | `venv\Scripts\python.exe` | ~0.6 MB | Spawns worker, holds venv |
| **Worker** | `C:\Python314\python.exe` | 600 MB idle → 1-2 GB indexing | Real MCP server, holds LanceDB handles |

Both processes write to the **same LanceDB directory** (`.codebase_indices/lancedb_v2/`). This is the root cause of the `Not found` bug — `rmtree` in one process while the other holds open handles.

---

## Core Components

### 1. Indexer (`src/core/indexing/indexer.py`)

**Responsibilities:**
- File discovery & parsing (Tree-sitter + Python AST)
- Embedding generation via ONNX embedder
- LanceDB write (vector + metadata)
- FTS5 incremental sync
- Symbol extraction → PropertyGraph

**Key Methods:**
- `index_project()` — full reindex (called by auto-index & manual trigger)
- `_index_single_file()` — incremental file update
- `apply_file_move()` — fast meta-patching for renames
- `notify_change()` → fire-and-forget queue

**FTS5 Sync Points:**
```python
# After LanceDB write in _index_single_file:
if self.searcher and hasattr(self.searcher, "incremental_update_fts5"):
    fts5_chunks = self._build_fts5_chunks_from_parsed(rel_path, parsed)
    self.searcher.incremental_update_fts5(fts5_chunks)

# On file move:
if self.searcher and hasattr(self.searcher, 'remove_from_fts5'):
    self.searcher.remove_from_fts5(old_path)
```

### 2. Searcher (`src/core/search/engine.py`)

**Hybrid Search Pipeline:**
```
Query
  │
  ├─► BM25 (sparse) ──►
  ├─► Dense (vector) ──► 3-way RRF (k=60) ──► MMR ──► Reranker (BGE-M3) ──► Results
  └─► FTS5 (full-text) ─►
```

**Modes:**
| Mode | Latency | Components | Reranker |
|------|---------|------------|----------|
| `fast` | ~1.6s | Dense + FTS5 + BM25 | ❌ |
| `quality` | ~4-5s | All + Reranker | ✅ |
| `deep` | 2-5s | + Graph analysis | ✅ |

**FTS5 Integration:**
- `_fts5_search()` — lazy builds FTS5 index from LanceDB (to_pandas ~0.6s first call)
- `reciprocal_rank_fusion_3way(bm25, dense, fts5, limit, k=60)` — merges 3 ranked lists
- `asyncio.wait_for(2.0)` guard on FTS5 — prevents timeout cascade

### 3. FTS5 Mixin (`src/core/search/fts5_mixin.py`)

**4-Tier FTS5 Index:**
| Table | Tokenizer | Purpose |
|-------|-----------|---------|
| `names_fts` | porter | Symbol names (class/func) |
| `chunks` | LIKE (substring) | Fallback substring |
| `content_fts` | trigram | Code content |
| `docs_fts` | porter+unicode61 | Docstrings |

**Key Methods:**
- `_build_fts5_index()` — lazy build from LanceDB (to_pandas)
- `incremental_update_fts5(chunks)` — only if FTS5 already built
- `remove_from_fts5(file_path)` — on file move/delete
- `_fts5_search()` — returns `source="fts5_hybrid"` for RRF key

### 4. LanceDB Manager (`src/core/indexing/db_manager.py`)

**3-Layer Defense (Triad Protection):**
```
Layer 1 (fast-fail): _reindex_guard (Event)
  → search fast-fails во время reindex
  → set_reindexing() / clear_reindexing()

Layer 2 (thread-safety): _write_lock (Lock)
  → сериализует write/reconnect между потоками одного процесса
  → begin_write() — context manager

Layer 3 (process isolation): _pid_lock (файловый lock с PID)
  → атомарный lock-файл .write_lock в директории БД
  → ТОЛЬКО ОДИН worker-процесс пишет в БД
  → Stale lock detection + auto-steal (если holder мёртв)
  → Lock released в __del__

Пример потоков данных:
  trigger_async_reindex() (layer.py)
    ├─ set_reindexing()  → Layer 1 guard включён
    ├─ run_in_executor → index_project()
    │    └─ IndexProjectRunner.run()
    │         ├─ begin_write()  → Layer 2 write lock
    │         ├─ парсинг + эмбеддинг
    │         ├─ запись в БД
    │         └─ _safe_ivf_index() → self-healing на Not Found
    └─ clear_reindexing() → Layer 1 guard выключен

PID-lock (Layer 3) захвачен в __init__ и держится всё время жизни Indexer.
```

```python
_write_lock = threading.Lock()           # Layer 2: Serializes write/reconnect
_reindex_guard = threading.Event()       # Layer 1: Search fast-fails during reindex
_pid_lock_path = self.db_path / ".write_lock"  # Layer 3: Process isolation

def set_reindexing(self):   self._reindex_guard.set()
def clear_reindexing(self): self._reindex_guard.clear()
def begin_write(self):      return self._write_lock
def is_reindexing(self):    return self._reindex_guard.is_set()
```

**Self-Healing:**
- `_reset_table_if_not_found()` — при Not Found: reset_connection + retry (до 2 попыток)
- `_safe_optimize()` — optimize с self-healing
- `_safe_create_index()` — create_index с self-healing
- `reset_connection()` — под lock, thread-safe, восстанавливает таблицу

**Connection Management:**
- `reset_connection()` — closes DB, reconnects, reopens table, rebuilds IndexGuard
- `_open_or_create_table()` — handles dimension mismatch (drop+recreate)
- `switch_db()` — multi-project support

### 5. Intelligence Layer (`src/core/intelligence/layer.py`)

**13 High-Level Tools:**
| Tool | Purpose |
|------|---------|
| `intel_get_runtime_status` | Aggregated health (embedder, reranker, index, system) |
| `intel_trigger_reindex` | Async full/incremental reindex (job-based) |
| `intel_get_job_status` | Poll reindex progress (ETA, chunks/s) |
| `intel_get_project_memory` | ADR, tech debt, known issues |
| `intel_code_topology` | Call graph, references for symbol |
| `intel_predict_root_cause` | ML-based error diagnosis |
| `intel_analyze_incident` | Similar past incidents |
| `intel_get_hotspots` | Riskiest files (churn + complexity) |
| `intel_get_telemetry` | Tool success rates, latency |
| `intel_auto_collect_adrs` | Git log → ADR extraction |
| `intel_explain_project_state` | Human-readable diagnosis |
| `intel_get_project_context` | Full snapshot (state+index+bridge+memory) |
| `intel_execution_timeline` | Recent operations timeline |

### 6. Runtime Coordinator (`src/core/runtime_coordinator.py`)

**Single Entry Point for Tool Execution:**
```python
async def can_execute(project_path, tool_name) -> ExecutionVerdict:
    # 1. ProjectContext.capture() — path, bridge, registry
    # 2. SystemArtifacts.check() — not system path
    # 3. Registry.get_state() — UNINIT/STARTING/INDEXING/READY/FAILED
    # 4. Bridge.read() — LSP synced?
    # 5. Returns ok/blocked with reason + retry_after
```

---

## Data Flow: Indexing

```
File Change (LSP didSave / manual trigger)
         │
         ▼
notify_change(file_path) ──► Fire-and-forget queue
         │
         ▼
Indexer._index_single_file()
         │
         ├─► Parse (Tree-sitter/AST) → chunks + symbols
         ├─► Embed (ONNX batch) → vectors
         ├─► LanceDB write (delete old + add new) ──► FTS5 incremental_update_fts5()
         └─► SymbolIndex update (PropertyGraph)
```

---

## Data Flow: Search

```
search_code(query, mode="fast")
         │
         ▼
SearchCodeTool.execute()
         │
         ▼
Searcher.search_with_mode(mode="fast")
         │
         ├─► Dense vector search (LanceDB)
         ├─► BM25 search (in-memory, lazy rebuild)
         └─► FTS5 search (lazy build from LanceDB)
         │
         ▼
3-way Reciprocal Rank Fusion (k=60)
         │
         ▼
MMR Diversity (optional)
         │
         ▼
Reranker (BGE-M3) — only in quality/deep
         │
         ▼
Format → UI items with 🔍fts5 / 🔤bm25 / 🧠dense badges
```

---

## Critical Bugs Fixed (2026-07-20)

### 1. LanceDB `Not found` during Finalizing

**Root Cause:** `intel_trigger_reindex(full)` used `shutil.rmtree('.codebase_indices')` while worker process held `self.table` open → dangling reference → `lance error: Not found` on Pruning/optimize. Также: два MCP-процесса (launcher + worker) писали в одну БД без блокировки → race condition.

**Fix (3-layer defense + PID-lock):**
1. **tools_reg.py**: Atomic `drop_table` + `create_table` + `reset_connection()` instead of `rmtree`
2. **indexer_table.py**: `_safe_read_arrow()` catches `Not found`/`LanceError` → `reset_connection()` + retry
3. **index_project_runner.py**: `_safe_optimize()` + `_safe_create_index()` with reset+retry on `Not found`
4. **db_manager.py**: PID-lock на директорию БД (Layer 3) — атомарный lock-файл с PID. Второй процесс ждёт или падает.
5. **server_factory.py**: Auto-index обёрнут в set_reindexing/clear_reindexing guard.

### 2. Auto-Index Silent Failure

**Root Cause:** `_auto()` task created via `ensure_future` in non-running loop; no logging; `FileGuard`/`embedder.is_ready()` could block silently; no `set_reindexing()` guard перед вызовом.

**Fix:** `server_factory.py` — `asyncio.create_task()` + explicit logging (`🚀 Auto-index: task created`, `starting background indexing task`, `completed`). + Guard: `set_reindexing()` перед `index_project()`, `clear_reindexing()` в finally.

### 3. FTS5 Visibility

**Root Cause:** `metadata.source` not propagated to UI formatter; `quality` mode reranker buried FTS5 results.

**Fix:** `search_tools.py` passes `source` → `ui_formatter.py` shows `🔍fts5` / `🔤bm25` / `🧠dense` badges. FTS5 guaranteed visible in `fast` mode (no reranker).

---

## Configuration

### Environment Variables
| Variable | Default | Purpose |
|----------|---------|---------|
| `PROJECT_PATH` | `$ZED_WORKTREE_ROOT` | Project root for indexing |
| `MSCODEBASE_ALLOW_SELF_INDEX` | false | Allow indexing extension itself |
| `MSCODEBASE_EXECUTE_SCRIPT_ENABLED` | false | Enable execute_script tool |
| `ONNX_MAX_LENGTH` | 128 | Token limit per chunk |
| `ONNX_BATCH_SIZE` | 4 | Embedding batch size |

### Key Paths
```
Extension:     %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\
Index DB:      <project>\.codebase_indices\lancedb_v2\index_<hash>.db\
Logs:          <ext>\.codebase_indices\logs\mscodebase-intelligence.log
Models:        <ext>\models\ (ONNX) + <ext>\llama_msvc\ (reranker)
```

---

## IndexProjectRunner with Self-Healing

`IndexProjectRunner` (`src/core/indexing/index_project_runner.py`) — оркестратор полной индексации.

**Ключевые изменения (v3):**
- Использует `db_manager.begin_write()` для сериализации записи (Layer 2)
- `_reset_table_if_not_found()` — self-healing при Not Found: reset_connection + retry
- `_safe_prune()` — prune с self-healing
- `_safe_ivf_index()` — optimize + create_index с self-healing
- PID-lock (Layer 3) захвачен в `db_manager.__init__()`, не дублируется в runner

**Поток индексации:**
```
Indexer.index_project()
  └─ IndexProjectRunner.run()
       ├─ begin_write() (Layer 2 lock)
       ├─ Phase 1: Parallel Parse (ThreadPoolExecutor, 4 workers)
       ├─ Phase 2: Sort + Batch Embed (batch=4, EMA speed tracking)
       ├─ Phase 3: Write Results (с self-healing on Not Found)
       ├─ _safe_prune() (с self-healing on Not Found)
       ├─ BM25 reindex
       └─ _safe_ivf_index() (optimize + create_index, self-healing)
```

## Testing

```bash
# Core FTS5 + search
pytest tests/test_fts5_integration.py -v
pytest tests/test_search_code_fts5_marker.py -v

# Indexer sync
pytest tests/test_indexer_fts5_sync.py -v

# Notify change (non-blocking)
pytest tests/test_notify_change_nonblocking.py -v
pytest tests/test_notify_change_fire_and_forget.py -v

# Full suite
pytest tests/ -v --timeout=120
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Not found: .../data/<hash>.lance` | rmtree while handles open | Use `intel_trigger_reindex(full)` (fixed) |
| Auto-index never starts | Task not scheduled / loop not running | Check logs for `🚀 Auto-index: task created` |
| Search returns 0 results | Index empty / embedder not ready | `intel_get_runtime_status` → check chunks > 0 |
| Reranker offline | llama-server not started / GGUF missing | Check `models/bge-m3-Q4_K_M.gguf` exists |
| Two MCP processes | Normal (launcher + worker) | Verify only ONE worker (C:\Python314\python.exe) |

---

## Development Workflow

```bash
# 1. Edit source in D:\Project\MSCodeBase\src\
# 2. Copy to extension:
cp src/core/search/engine.py /c/Users/misha/AppData/Local/Zed/extensions/mscodebase-intelligence/src/core/search/
# 3. Reload Window in Zed (Ctrl+Shift+P → Reload Window)
# 4. Test: intel_trigger_reindex(full) → intel_get_job_status → search_code
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/mcp/server.py` | MCP entry point, tool registration |
| `src/mcp/server_factory.py` | Auto-index trigger, extension handlers |
| `src/core/intelligence/layer.py` | Intel layer (13 tools) |
| `src/core/intelligence/tools_reg.py` | `intel_trigger_reindex` implementation |
| `src/core/indexing/indexer.py` | Core indexing logic |
| `src/core/indexing/indexer_table.py` | LanceDB table ops + FTS5 sync |
| `src/core/indexing/index_project_runner.py` | Full reindex orchestration |
| `src/core/indexing/db_manager.py` | LanceDB connection + guards |
| `src/core/search/engine.py` | Hybrid search pipeline |
| `src/core/search/fts5_mixin.py` | FTS5 4-tier index |
| `src/core/search/scoring.py` | RRF, MMR, bucket weights |
| `src/core/search/bm25.py` | BM25 sparse retrieval |
| `src/core/search/agentic_search.py` | Agentic/deep mode |
| `src/core/indexing/resource_monitor.py` | RAM/CPU guards |
| `src/utils/ui_formatter.py` | Search result formatting (badges) |

---

*Generated: 2026-07-20 | Version: 9301b950*