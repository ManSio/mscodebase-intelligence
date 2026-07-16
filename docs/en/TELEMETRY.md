# Telemetry — MCP Runtime Metrics Collection

[🇬🇧 English](TELEMETRY.md) • [🇷🇺 Русский](../ru/TELEMETRY.md) • [🇨🇳 中文](../zh/TELEMETRY.md)

Automatic metrics collection for building graphs and performance analysis.

## How It Works

Two independent telemetry systems collect metrics:

### 1. Per-Tool Metrics (in-process, auto-persisted)

Every call to any MCP tool is automatically recorded by the `error_boundary` decorator.
Metrics are kept in memory and saved to JSON every 10 calls + on shutdown:

```
{ext_root}/telemetry/tool_metrics.json
```

**Example table** (visible via `intel_get_telemetry`):

| Tool | Calls | Errors | Min ms | Avg ms | Max ms | Last call |
|------|-------|--------|--------|--------|--------|-----------|
| search_code | 31 | 0 | 1676 | 2525 | 14264 | 23:04:41 |
| structural_search | 20 | 0 | 35 | 2179 | 4479 | 23:07:44 |
| impact_analysis | 4 | 0 | 1343 | 1353 | 1370 | 23:03:49 |
| get_symbol_info | 3 | 0 | 1332 | 1338 | 1348 | 23:00:55 |

Metrics persist across MCP server restarts — `load_metrics()` reads the saved JSON on startup.

### 2. External Collector (scheduled snapshots)

The script `scripts/collect_telemetry.py` captures a snapshot of all runtime counters
and saves it to a JSON file with the date. Files accumulate in the directory:

```
.mscodebase/telemetry/
├── 2026-07-05.json    ← all snapshots for July 5
├── 2026-07-06.json    ← all snapshots for July 6
└── ...
```

Each file is an array of records:
```json
[
  {
    "date": "2026-07-05",
    "captured_at": "2026-07-05T23:00:00",
    "uptime_sec": 43200,
    "counters": {
      "can_execute_calls": 152,
      "verdict_ready": 148,
      "verdict_blocked_not_ready": 3,
      "verdict_blocked_system_path": 0,
      "total_wait_time_sec": 2.4,
      "warnings_bridge_not_synced": 1,
      "warnings_indexing_in_progress": 2
    },
    "project": {
      "project_path": "D:\\Project\\MSCodeBase",
      "state": "READY",
      "index_chunks": 1362,
      "index_files": 106,
      "index_symbols": 1080,
      "index_latency_ms": 13.2
    }
  }
]
```

### 🔗 Related Documents

| Document | Description |
|----------|-------------|
| [README.md](../README.md) | Main documentation, map of all docs |
| [TELEMETRY.md](TELEMETRY.md) | This file |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [KNOWN_ISSUES.md](../KNOWN_ISSUES.md) | Known issues, including RAM profile (KI-002) |

## Usage

### One-time collection
```bash
python scripts/collect_telemetry.py
```

### Schedule daily collection at 23:00
```bash
python scripts/collect_telemetry.py --daily
```
Creates a Windows Task Scheduler task "MSCodeBase Telemetry Collector".

### View history for N days
```bash
python scripts/collect_telemetry.py --history 7
```
Outputs JSON for the last 7 days.

## Collected Metrics

### Runtime Counters (from RuntimeCoordinator)

| Metric | What it shows |
|--------|---------------|
| `can_execute_calls` | How many times MCP checked project readiness |
| `verdict_ready` | How many times the project was ready (normal) |
| `verdict_blocked_not_ready` | How many times the project was not ready (reindex needed) |
| `verdict_blocked_system_path` | How many times an attempt was made to work with a system directory |
| `verdict_blocked_failed` | How many times the project failed to initialize |
| `verdict_blocked_resolution` | How many times project resolution failed |
| `verdict_blocked_registry_error` | How many times the Registry errored |
| `warnings_bridge_not_synced` | How many times LSP was not synchronized |
| `warnings_indexing_in_progress` | How many times indexing was in progress |
| `warnings_just_started` | How many times MCP just started |
| `total_wait_time_sec` | How many seconds MCP waited for project readiness |

### Project Statistics

| Metric | What it shows |
|--------|---------------|
| `state` | Current project state (READY/INDEXING/FAILED) |
| `index_chunks` | Number of chunks in LanceDB |
| `index_files` | Number of indexed files |
| `index_symbols` | Number of recognized Tree-sitter symbols |
| `index_latency_ms` | Time to retrieve index status |

### Passport

| Metric | What it shows |
|--------|---------------|
| `uptime_sec` | How many seconds the MCP process has been running |
| `run_id` | Unique run ID |
| `build_id` | Git commit hash |

## Live Telemetry Tools (MCP)

Besides the background collector (`scripts/collect_telemetry.py`), metrics are available
live through MCP tools:

### `intel_get_telemetry`
Runtime snapshot of the process:
- **Runtime State**: Ready/Blocked, Warnings, Total wait
- **Per-Tool Calls**: table `Tool | Calls | Errors | Min/Avg/Max ms | Last call`
- **Resources**: `RAM` (MB), `CPU` (%), `Threads`
- **LLM Provider**: model, ping, batch-10 latency, throughput (tok/s)
- **ETA Predictor**: `Total measurements`, `Learned: N/8 ops`
- **History**: last snapshots (date / chunks / files / RAM / LLM ping)

### `intel_execution_timeline`
Table of recent calls: `Time | Tool | ms | Status | Route | Confidence | Results`.
Shows the real per-tool latency in a live session.

### `get_runtime_counters`
- `Checks` / `Ready` / `Blocked` (%)
- `Blocks` (list of blocked calls)
- `Warnings`, `Performance.Wait`

### `debug_runtime_passport`
Extended passport: `RUN_ID`, `BUILD_ID`, `PID`, `Uptime`, `CWD`, `Ext Root`,
`Bridge State`, `Registry` (paths, cached projects, hits/misses), `Env` (PROJECT_PATH, PYTHONPATH).

### `intel_tool_health`
Per-tool health dashboard: success rate, latency, confidence, routes.

### Example (live run 2026-07-12)

| Tool | Calls | Avg ms | Status |
|------|-------|--------|--------|
| get_index_status | 1 | 295 | ✅ |
| get_symbol_info | 1 | 1611 | ✅ |
| impact_analysis | 1 | 1588 | ✅ |
| search_code | 1 | 1651 | ✅ |
| rename_symbol | 1 | 2624 | ✅ (preview) |
| get_health_report | 1 | 21618 | ✅ (heavy: log scan) |

> `get_health_report` ~21s — normal, it scans logs and builds a full report.
> MCP server RAM at idle ~1GB, peak under load ~2.8GB (NOT a leak, see KNOWN_ISSUES KI-002).

---

## Model Pipeline (actual, 2026-07-12)

The embedding/rerank pipeline is **local and in-process** — no external LLM server is
required for semantic search:

| Stage | Engine | Model | Notes |
|-------|--------|-------|-------|
| Embedding | ONNX INT8 / OpenVINO INT8 (in-process) | `intfloat/multilingual-e5-base` (768-dim) | ~350 ch/s on Windows CPU. File: `model_quantized.onnx`. LM Studio is a **fallback provider only**. |
| Reranker | llama.cpp (`llama-server.exe`, separate process, `:8081`) | `BAAI/bge-reranker-v2-m3` (GGUF Q4_K_M) | Loaded by `step_gguf` in `install.py`. |
| LLM (RAG, optional) | reserved | — | Not required for search. |

> ⚠️ **Doc drift fixed (2026-07-12):** Older telemetry docs described "LM Studio
> bge-m3 / phi-4-mini" as the embedding provider. That is **out of date** — embedding
> moved in-process to ONNX/OpenVINO E5-base INT8 (see CHANGELOG 3.2.1). LM Studio remains
> only an optional fallback if the local ONNX/OpenVINO model is unavailable.

---

## Building Graphs

Accumulated JSON files can be loaded into any BI system:

- **Excel** — JSON import via Power Query
- **Grafana** — if you add an HTTP server serving these files
- **Python/matplotlib** — `python scripts/collect_telemetry.py --history 30`

## What's Considered Normal

| Metric | Good | Concerning |
|--------|------|------------|
| `verdict_ready / can_execute_calls` | > 95% | < 80% |
| `verdict_blocked_not_ready` | < 5% | > 20% |
| `verdict_blocked_system_path` | 0 | > 1 |
| `total_wait_time_sec` | < 10s/day | > 60s/day |
| `warnings_bridge_not_synced` | < 3/day | > 20/day |
| `index_latency_ms` | < 50ms | > 500ms |
| MCP RAM (idle) | ~1.0 GB | > 2.0 GB sustained at idle |
| MCP RAM (peak under load) | < 3.0 GB transient | sustained > 3.0 GB |

## 📊 Search Stress Test (2026-07-07)

17 `search_code` calls — **0 errors, 0 timeouts, P@5=1.00**

### Search Mode Performance

| Mode | Query | Time | Top-1 | Noise |
|------|-------|------|-------|-------|
| `fast` | `class MultiProviderReranker` | **315ms** | `reranker.py` code | 0/5 ✅ |
| `fast` | `TaskQueue` | 374ms | `task_queue.py` code | 0/6 ✅ |
| `fast` | `def can_execute` | 363ms | `runtime_coordinator.py` code | 0/6 ✅ |
| `quality` | `memory leak gc objects` | **426ms** | AGENT_DIARY.md + `intelligence_layer.py` code | 0/5 ✅ |
| `quality` | `dependency injection` | 486ms | CHANGELOG.md docs | 0/5 ✅ |
| `quality` | `RuntimeCoordinator bridge` | 1567ms | AGENTS.md architecture | 0/5 ✅ |
| `deep` | `почему MCP не отвечает` | **~3s** | `docs/ru/FAQ.md` Russian docs | 0/5 ✅ |
| `deep` | `мульти-оконность` | ~5.3s | `docs/ru/ARCHITECTURE.md` | 0/5 ✅ |

### Pipeline Latency (5 chunks `quality`)

| Stage | Engine | Time |
|-------|--------|------|
| Vector search | LanceDB | ~300ms |
| Rerank | bge-reranker-v2-m3 (cosine sim) | ~200ms |
| **Total** | | **~500ms** |

### Verdict

| Aspect | Status |
|--------|--------|
| Stability | ✅ 20/20 successful |
| Accuracy | ✅ P@5=1.00 |
| Speed | ✅ 500ms–5s depending on mode |
| Memory leak | ⚠️ None — idle ~1GB, transient peak ~2.8GB (KI-002) |

---

## 📊 Live Tool Audit (2026-07-12)

Full load test: **all 59 registered tools** called live through the real MCP server.

### Tool surface
- **33 tools total** = 16 core + 14 intel + 3 diagnostic (per server startup log).
- **Default filter**: only **12 tools** are visible unless `MSCODEBASE_MCP_TOOLS` is set.
  Set `MSCODEBASE_MCP_TOOLS=""` to show all 59. Set a comma list to show a subset.
- ~19 tools return live data; ~36 are hidden by the default filter (by design, NOT a bug).

### Per-tool latency (live run)

| Tool | Calls | Avg ms | Status |
|------|-------|--------|--------|
| get_index_status | 1 | 295 | ✅ |
| get_symbol_info | 1 | 1611 | ✅ |
| impact_analysis | 1 | 1588 | ✅ |
| search_code | 1 | 1651 | ✅ |
| replace_symbol | 1 | 1598 | ✅ (preview) |
| rename_symbol | 1 | 2624 | ✅ (preview) |
| get_health_report | 1 | 21618 | ✅ (heavy: log scan) |

### Bugs found & fixed during the audit (see KNOWN_ISSUES / CHANGELOG 3.2.1)
- **INC-58EA** — IVF index "0 vectors": `_init_onnx` loaded `model.onnx` but the file on
  disk is `model_quantized.onnx` → embedder returned zeros → all vectors had norm 0.0 →
  KMeans failed. Fixed: `_init_onnx` now prefers `model_quantized.onnx` (like `_init_openvino`).
- **INC-9573** — `intel_get_runtime_status` showed `symbol_index_count: 0` while
  `get_health_report` showed `3197`. Fixed: use live `get_symbol_count()` + disk reload.
- **INC-0AA6** — job hung at 80% "Finalizing": `await future_symbols` (Tree-sitter symbol
  indexing) had no timeout. Fixed: `asyncio.wait_for(..., timeout=120)` with graceful job completion.

### RAM profile (measured via `psutil`)
- Idle MCP ~1.0 GB, reindex peak ~1.1 GB, transient 2.8 GB under load.
- Confirmed **NOT a leak**: the 2.8 GB transient was an orphaned benchmark subprocess
  (`PID 15620`) which was killed; steady-state RSS returned to ~1.0 GB.
