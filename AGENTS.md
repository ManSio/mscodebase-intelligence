# Project Agent Rules — MSCodeBase Hybrid Architecture (43 Registered Tools)

> Global system prompt / context injection for the AI Agent in Zed IDE. Applied across all projects.
> Optimized for the hybrid model: 10 High-Level Intelligence Tools + 33 Low-Level Core MCP Tools.

## 0. FIRST STEP IN ANY SESSION

1. **Read the Diary:** Review the first 5 entries in `AGENT_DIARY.md` (if the file exists in the project root).
2. **Determine MCP Context:**
   - If `intel_*` tools or `search_code` are available → Full Hybrid Context Mode.
   - If absent → MCP server offline. Work exclusively with `grep`, `read_file`, `terminal`.
3. **Runtime Check:** Call `intel_get_runtime_status`. If it fails with pipe/transport error → switch to grep/cat fallback.
4. **Load Project Memory:** Call `intel_get_project_memory()` to learn ADRs, known issues, tech debt.

## 1. TOOL SELECTION

### 1.1 Architectural Substitution Rules

| Instead of | Use |
|---|---|
| `get_index_status` + `watcher_status` | `intel_get_runtime_status` |
| `index_project_dir` (blocking) | `intel_trigger_reindex` (fire-and-forget) |
| Multiple low-level calls | `intel_get_project_context` (one snapshot) |
| Parsing raw logs | `intel_predict_root_cause` or `intel_analyze_incident` |

### 1.2 Search Code Mode Matrix

`search_code(query, mode="auto")` is the ONLY search tool. `smart_search`, `deep_search`, `context_search` are DEPRECATED.

| Mode | When | Speed |
|---|---|---|
| `"fast"` | Exact file/variable name lookup | ~300ms |
| `"quality"` | Logic, architecture, relationships (default) | ~1200ms |
| `"deep"` | Complex architectural investigation | ~2-5s |
| `"context"` | Find similar code by code fragment | ~500ms |
| `"auto"` | Auto-detect: simple→fast, complex→agentic | ~300ms-2s |

### 1.3 Priority Matrix

```
[ANALYSIS / BRAIN]                  [SURGICAL ACTION]               [FALLBACK]
High-Level Intel Tools              Low-Level Core MCP              Built-in IDE
──────────────────────              ──────────────────────          ───────────
intel_get_runtime_status      ──>   get_index_status / watcher     grep (exact)
intel_trigger_reindex         ──>   notify_change                  grep (fallback)
intel_code_topology           ──>   get_symbol_info / structural   grep
intel_predict_root_cause      ──>   get_logs / get_health_report   terminal cat
intel_get_project_memory      ──>   get_commit_history / file_hist (no analog)
intel_get_project_context     ──>   (aggregates 5+ calls)
```

## 2. AVAILABLE TOOLS (43)

### A. High-Level Intelligence Layer (10 tools)

`intel_get_runtime_status`, `intel_trigger_reindex`, `intel_get_job_status`,
`intel_code_topology`, `intel_log_incident`, `intel_analyze_incident`,
`intel_add_memory_node`, `intel_get_project_memory`, `intel_get_project_context`,
`intel_explain_project_state`.

Diagnostic: `debug_runtime_passport`, `get_runtime_counters`.

### B. Low-Level Core MCP & Search (33 tools)

`search_code(mode=fast|quality|deep|context|auto)`, `cross_repo_search`,
`cross_project_deps`, `get_symbol_info`, `impact_analysis`, `get_repo_map`,
`get_repo_rank`, `get_hotspots`, `get_bug_correlation`, `get_related_files`,
`graph_query`, `get_index_status`, `get_index_progress`, `get_index_timeline`,
`index_health`, `index_project_dir`, `notify_change`, `watcher_status`,
`get_logs`, `get_health_report`, `run_health_check`, `get_commit_history`,
`get_file_history`, `get_branch_info`, `generate_chunk_summaries`,
`scan_changes`, `find_similar_bugs`, `predict_eta`, `verify_action`,
`get_task_status`, `submit_background_task`, `read_live_file`,
`structural_search`.

> **Deprecated** (use `search_code`): `smart_search`, `deep_search`, `context_search`.

## 3. STATE AWARENESS

- If `get_index_status` returns 0 chunks → FORBIDDEN to use `search_code`. Switch to `grep`/regex.
- If chunks > 0 → use `search_code` for semantic, `get_symbol_info` for exact names.

## 4. MEMORY PROTOCOL

1. **Start:** Call `intel_get_project_memory()`. Study ADRs, known issues, past attempts.
2. **After task:** Call `intel_log_incident()` with component, symptom, root_cause, fix, success.
3. **If you notice an anti-pattern:** Call `intel_add_memory_node(section="tech_debt", data_json=...)`.

## 5. EXECUTION CONTRACT

### Reconnaissance
- NEVER guess line numbers. Use `get_symbol_info` or `grep` before `read_file`.
- CONTEXT BUDGET: Max 50 lines per `read_file` call. NEVER ingest entire files.
- SAFE WRITING: Read target lines before edit. Preserve indentation and style.

### Post-Modification
After `edit_file` / `write_file` → `notify_change(file_path=...)` → `get_index_status()`.
Use batch notify: `notify_change(file_path=["src/a.py", "src/b.py"])`.

### Error Handling
- Do not retry same tool with same params. Pivot to alternative.
- If MCP fails → grep/cat → find_path → terminal.
- After failed hypothesis twice → STOP. Pivot to different hypothesis.

### Windows Paths
- MCP tools: Windows escaped format (`src\\core\\config.py`).
- Terminal (GitBash): POSIX format (`src/core/config.py`).

## 6. ABSOLUTE FORBIDDENS

### Deprecated
- `smart_search`, `deep_search`, `context_search` — DEPRECATED. Use `search_code(mode=...)`.
- `index_project_dir` (blocking) — Use `intel_trigger_reindex` (async).

### Architecture
- Tools must NOT call Registry, Bridge, or Passport directly. Use `RuntimeCoordinator.can_execute()` + `ProjectContext.capture()`.
- RuntimeCoordinator must NOT know about Search, Indexer, or Memory.
- New components must answer: "Which existing layer does it extend?"
- One class = one responsibility.

### Environment
- NO Docker, NO WSL, NO pytz (use zoneinfo).
- NO stubs, TODOs, or placeholders. Every change = production-ready.
- NO debug prints to stdout (breaks JSON-RPC parser).
- NO investigating a hypothesis after two consecutive observations confirm the same fact.

## 7. SELF-CHECK BEFORE COMPLETING

1. Did I update the index after writing? (`notify_change` + `get_index_status`)
2. Are paths in correct format? (Windows for MCP, POSIX for terminal)
3. Did I avoid retrying failed tools?
4. Is the code production-ready (no stubs/TODOs)?
5. Did I update `AGENT_DIARY.md`?
6. Did I log the incident in project memory? (`intel_log_incident`)
7. Did I check `diagnostics`?
8. All correct? → **TASK VERIFIED**
