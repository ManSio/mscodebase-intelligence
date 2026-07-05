# Telemetry — MCP Runtime Metrics Collection

[🇬🇧 English](TELEMETRY.md) • [🇷🇺 Русский](../ru/TELEMETRY.md) • [🇨🇳 中文](../zh/TELEMETRY.md)

Automatic metrics collection for building graphs and performance analysis.

## How It Works

The script `scripts/collect_telemetry.py` captures a snapshot of all runtime counters
and saves it to a JSON file with the date. Files accumulate in the directory:

```
.mscodebase/telemetry/
├── 2026-07-05.json    ← all snapshots for July 5
├── 2026-07-06.json    ← all snapshots for July 6
└── ...

---

### 🔗 Related Documents

| Document | Description |
|----------|-------------|
| [README.md](README.md) | Main documentation, map of all docs |
| [TELEMETRY.md](TELEMETRY.md) | This file |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
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
