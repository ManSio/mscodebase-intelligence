# Bug Report: Zed OOM crash — agent_ui memory leak leads to 4-6 GB resident, app_will_quit timeout

> **Type:** Bug / Crash
> **Platform:** Windows
> **Priority:** P1 (crash, reproducible)
> **Status:** Draft — готов к публикации на https://github.com/zed-industries/zed/issues/new

---

## Description

Zed crashes with `app_will_quit timeout` → `window not found` cascade when memory reaches 4-6 GB resident. Unlike #60475 (STATUS_STACK_BUFFER_OVERRUN fixed by GPU driver update), this is a pure OOM crash.

## Crash signature

```
ERROR [gpui::app] timed out waiting on app_will_quit
ERROR [crates/gpui/src/window.rs:1472] window not found
ERROR [crates/gpui/src/window.rs:1516] window not found
... (5-10 repeated)
→ 4 seconds later → restart
```

No exception code — no `0xc0000409`, no `0xc0000005`. The GPU driver fix from #60475 did NOT affect this crash.

## Crash data

### 18 crashes confirmed in 3 days (July 8-11, 2026)

| # | Date | Time | Version | Resident | Virtual | Pre-crash pattern |
|---|------|------|---------|----------|---------|-------------------|
| 1 | 08.07 | 02:38 | v1.9.0 | 712 MB | 1469 MB | app_will_quit timeout |
| 2 | 08.07 | 23:56 | v1.9.0 | **6173 MB** | **9081 MB** | app_will_quit timeout |
| 3 | 09.07 | 06:42 | v1.9.0 | 976 MB | 4212 MB | app_will_quit timeout |
| 4 | 09.07 | 19:16 | v1.10.0 | 239 MB | 228 MB | window not found ×5 |
| 5 | 09.07 | 22:12 | v1.10.0 | — | — | (cold restart) |
| 6 | 09.07 | 22:22 | v1.10.0 | — | — | (cold restart) |
| 7 | 09.07 | 22:30 | v1.10.0 | — | — | (cold restart) |
| 8 | 10.07 | 07:44 | v1.10.1 | — | — | window not found |
| 9 | 10.07 | 07:50 | v1.10.1 | — | — | (cold restart) |
| 10 | 10.07 | 07:59 | v1.10.1 | 632 MB | 700 MB | app_will_quit timeout |
| 11 | 10.07 | 08:03 | v1.10.1 | **4344 MB** | **5649 MB** | app_will_quit timeout |
| 12 | 10.07 | 08:32 | v1.10.1 | — | — | (cold restart) |
| 13 | 10.07 | 08:34 | v1.10.1 | — | — | (cold restart) |
| 14 | 10.07 | 15:17 | v1.10.2 | — | — | (cold restart) |
| 15 | 10.07 | 17:20 | v1.10.2 | **3745 MB** | **7074 MB** | app_will_quit timeout |
| 16 | 10.07 | 17:22 | v1.10.2 | — | — | (cold restart) |
| 17 | 10.07 | 18:25 | v1.10.2 | **4345 MB** | **6551 MB** | app_will_quit timeout |
| 18 | 11.07 | 09:20 | v1.10.2 | **4116 MB** | **6813 MB** | app_will_quit timeout |

**Memory peaks >3 GB: 12 confirmed instances** (full data in attached crash timeline)

## Memory growth pattern

Each session follows the same trajectory:
1. **Start:** ~50 MB (cold) or ~500 MB (warm restore)
2. **Agent UI session grows:** +200-500 MB per 10 tool calls
3. **Agent context expands:** +1000 MB when `spawn_agent` creates sub-agents
4. **GC fails:** memory plateaus at 2-3 GB but never releases
5. **Rapid acceleration:** +500-1000 MB in 30 seconds
6. **Crash:** `app_will_quit timeout` at 3.5-6 GB resident

## Root cause hypothesis

The crash is caused by the same underlying issue as #59442 (Background `agent_ui` SQLite write loop leaks memory to 53 GB):

1. `agent_ui` writes session state to `ScopedKeyValueStore` (SQLite) on every tool call
2. SQLite WAL file grows unbounded during long agent sessions (50-120+ turns)
3. `gpui::platform::windows` window management code holds references to growing data structures
4. When memory pressure hits, `app_will_quit` handler times out waiting for windows to close
5. `window not found` cascade indicates gpui window registry is in inconsistent state

Related: 
- #56347 — Multiple "LSP Edit" tabs accumulate during agent streaming edits, causing OOM (same mechanism — tabs accumulate without cleanup)
- #57126 — Zed agent memory usage rising fast until crash when editing files

## Reproduction steps

1. Open a mid-sized project (10k+ files, 2.5k index chunks)
2. Start a long agent session with `effort: high` or `xhigh`
3. Make 50-120+ tool calls (read_file, grep, terminal, search_code, spawn_agent)
4. Observe: memory grows 200-500 MB per 10 calls
5. At ~3 GB: agent UI becomes sluggish
6. At ~3.5-4 GB: crash within 5 minutes

## System

| Component | Details |
|-----------|---------|
| **OS** | Windows 11 Home Insider Preview, build 26220 |
| **CPU** | AMD Ryzen 5 5600H (6 cores) |
| **RAM** | 16 GB DDR4-3200 |
| **GPU** | AMD Radeon Graphics (Vega, integrated, 512 MB VRAM) |
| **GPU driver** | Latest Adrenalin (updated to fix #60475) |
| **Zed version** | 1.10.2+stable.322.adc60cc (also reproduced on 1.9.0, 1.10.0, 1.10.1) |
| **Model provider** | opencode (go/deepseek-v4-flash) |
| **effort** | high / xhigh |
| **Context server** | mscodebase-intelligence (Python MCP server) |

## Attachments

- Full crash timeline (including all memory usage logs): `ZED_CRASH_TIMELINE.md` (679 lines)
- Current `Zed.log`: available on request
- Previous `Zed.log.old`: available on request

## Workarounds

1. **Restart Zed every 30-60 minutes** during heavy agent usage
2. **Lower `effort`** from `xhigh` to `high` (reduces per-turn tool calls)
3. **Keep sessions short** — avoid 100+ tool calls in one session
4. **Monitor** with `.\tools\monitor_zed_memory.ps1 -ThresholdMB 2500` (see repo)
