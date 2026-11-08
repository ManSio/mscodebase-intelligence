# Telemetry

[English](TELEMETRY.md) · [Русский](../ru/TELEMETRY.md) · [中文](../zh/TELEMETRY.md)

> Version 3.5.0. Everything on this page is local. The server sends nothing to
> the network and has no analytics endpoint.

---

## 1. Two independent recorders

| Recorder | What it stores | Where it lives | Lifetime |
|---|---|---|---|
| Per-tool metrics | calls, errors, latency samples, repeat rate, route | `<ext_root>/telemetry/tool_metrics.json` | across restarts (written every 10 calls and on exit) |
| Daily snapshots | runtime counters, index size, RAM/CPU, provider ping | `<data_root>/projects/<hash8>/telemetry/YYYY-MM-DD.json` | 90 days, then pruned |

`<ext_root>` is the directory the code runs from
(`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`).
`<data_root>` is `%LOCALAPPDATA%\mscodebase` on Windows,
`~/Library/Caches/mscodebase` on macOS, `~/.cache/mscodebase` on Linux; override
with `MSCODEBASE_DATA_DIR`. `<hash8>` is `md5(normalised project path)[:8]`
(`artifact_paths.project_hash`).

Neither recorder is a log of user prompts. There is no request/response payload
storage: tool arguments and code text are not written to telemetry.

## 2. Per-tool metrics

`@error_boundary` calls `record_tool_call()` before and `record_tool_result()`
after each tool invocation. Per tool it keeps:

- `calls`, `errors`, `total_ms`, `min_ms`;
- a bounded latency sample (`deque(maxlen=1000)`) — P50/P95/P99 are computed from
  the **last 1000 calls**, not from all history;
- `repeat_count` (same tool called twice in a row) as a percentage of calls;
- idle time between calls, and a `route` counter when the tool reports one.

Persistence: an `atexit` handler plus a flush every 10 calls write the whole
registry to `<ext_root>/telemetry/tool_metrics.json` via a temp file and
`os.replace` (atomic, no half-written JSON). Metrics are **not** loaded back at
startup, so the file is a snapshot of completed sessions, not a cumulative
database.

Read it with:

| Tool | Profile | Returns |
|---|---|---|
| `intel_tool_health()` | full | health bar, calls, P50/P95, repeat %, routes, idle vs active % |
| `intel_execution_timeline(limit=15)` | full | last N calls with tool, ms, ok/fail, route, confidence |
| `intel_get_telemetry(days=7)` | full | runtime counters + tool summary + resources + provider ping + history |

`intel_get_telemetry` is the only one that also writes a snapshot (see §3).
There is no `get_index_status` tool — index state is
`codebase(action="index", path="status")`.

## 3. Daily snapshots

Each `intel_get_telemetry()` call appends one entry to
`<data_root>/projects/<hash8>/telemetry/<date>.json`. The file is a JSON array;
shape below, values illustrative:

```json
[{
  "date": "2026-11-08",
  "captured_at": "2026-11-08T12:34:56",
  "uptime_sec": 1234.5,
  "counters": { "can_execute_calls": 12, "verdict_ready": 12, "total_wait_time_sec": 0.0 },
  "project": { "project_path": "...", "index_chunks": 0, "index_files": 0 },
  "resources": { "rss_mb": 0, "cpu_percent": 0 },
  "llm": { "ping_ms": 0.0, "batch_10_ms": 0.0, "tokens_per_sec": 0,
           "provider": "fallback", "model": "...", "configured_model": "..." },
  "token_savings": { "avg_savings_percent": 95.0, "total_searches": 0 },
  "_meta": { "index_age_days": 0 }
}]
```

Notes on fields you might over-read:

- `llm` is measured by actually embedding `"ping"` and a batch of ten; if the
  provider is down the key is `{"error": ...}` instead. `provider` is the live
  mode (`onnx`, `llama_cpp`, `lm_studio`, `ollama`, `onnx_server`, `fallback`),
  not the configured preference.
- If a section fails, that section becomes `{"error": "..."}` — the snapshot is
  still written. A partial snapshot is a signal, not a broken file.
- `token_savings.avg_savings_percent` is a fixed constant in the writer, not a
  measurement. Do not quote it.

## 4. Runtime counters

`get_runtime_counters()` (full profile) formats `runtime_coordinator._COUNTERS`:
`can_execute_calls`, `verdict_ready`, `verdict_blocked_system_path`,
`verdict_blocked_not_ready`, `verdict_blocked_failed`,
`verdict_blocked_resolution`, `verdict_blocked_registry_error`,
`warnings_bridge_not_synced`, `warnings_indexing_in_progress`,
`warnings_just_started`, `total_wait_time_sec`.

With zero checks it prints "Checks: 0 — данных нет" rather than "100% blocked",
because a ratio over an empty denominator is not a measurement.

## 5. Standalone collector

For a snapshot without a running MCP session:

```bash
python scripts/collect_telemetry.py            # one snapshot into data_root/.../telemetry
python scripts/collect_telemetry.py --history 7 # print the last 7 days as JSON
python scripts/collect_telemetry.py --daily     # register a Windows scheduled task (23:00)
```

The scheduled task uses `pythonw.exe` when it exists, so it does not flash a
console window. The script resolves the project through
`resolve_project_root()` and writes through `artifact_paths.get_telemetry_dir()`,
so it never litters the project directory.

## 6. Resources

RAM/CPU come from `src/core/indexing/resource_monitor.py`
(`get_global_resource_monitor().get_summary()`), sampled by the monitor rather
than computed on demand. `get_health_report()` surfaces the same numbers plus
disk warnings: below `MIN_FREE_DISK_MB = 500` the data root gets a warning.

## 7. Retention and cleanup

`artifact_gc.prune_stale_artifacts()` runs in a background thread 3 s after
startup:

- telemetry files older than **90 days** are deleted;
- inactive project folders (no writes for **30 days**) are removed entirely,
  unless the project is active in the registry;
- logs older than **7 days** are pruned;
- locked files are skipped and reported, never force-deleted.

Defaults live in `artifact_gc.py` (`DEFAULT_TELEMETRY_MAX_AGE_DAYS`,
`DEFAULT_PROJECT_MAX_AGE_DAYS`, `DEFAULT_LOG_RETENTION_DAYS`).

## 8. Privacy summary

- Everything stays on the machine; there is no upload path in the code.
- No source text, prompt or tool argument is persisted.
- `read_live_file` contents, absolute paths from errors, and tracebacks are
  logged (not returned in responses); `src/core/redact.py` strips
  prefix-anchored credential shapes before text reaches an agent's context, and
  is explicitly not a boundary.
- Deleting `<data_root>/projects/<hash8>/telemetry/` is safe: it removes history
  and leaves the index, graph and memory untouched.

---

**Verified against:** `src/core/error_handler.py` (`record_tool_call`,
`get_tool_metrics_summary`, `set_metrics_path`, deque size, save cadence),
`src/mcp/server_factory.py` (`set_metrics_path(_ext_root/telemetry/...)`),
`src/core/intelligence/layer.py` (`intel_get_telemetry` snapshot writer),
`src/core/intelligence/tools_reg.py` (`intel_get_telemetry` registration),
`src/utils/ui_formatter.py` (`format_telemetry`),
`src/mcp/server_tools.py` (`get_runtime_counters`, `intel_tool_health`,
`intel_execution_timeline`), `src/core/runtime_coordinator.py` (counter names),
`src/core/artifact_paths.py` (data-root layout), `src/core/artifact_gc.py`
(retention), `scripts/collect_telemetry.py`, `src/core/redact.py`.
