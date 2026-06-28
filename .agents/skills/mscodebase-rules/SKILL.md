---
name: mscodebase-rules
description: "Tool selection rules for the Zed AI agent. Determines which tool to use depending on the task: grep, find_path, MCP search_code, deep_search, cross_repo_search, get_symbol_info, get_context, get_repo_map, scan_changes, context_search, structural_search, get_logs, get_index_progress. Use search_code(agentic=True) for complex multi-part questions."
---

# MSCodeBase Tool Selection Rules

## Tool Selection Matrix

| Scenario | Tool to Use | Rationale |
|---|---|---|
| Find a specific file by path or exact class/function name | `grep` / `find_path` | Instant, 100% exact match accuracy |
| Understand architecture, search by concept/intent, find relationships | MCP `search_code` | Semantic vector search connects abstract concepts |
| Complex research queries, multi-step investigation | MCP `deep_search` | Iterative search with query refinement across multiple passes |
| Cross-project search in mono-repos | MCP `cross_repo_search` | Search across multiple indexed projects with @-mention syntax |
| Rewrite a function and analyze what will break | MCP `get_symbol_info` (Call Graph) | Shows all dependent modules and inbound calls |
| Files created/deleted outside of Zed | MCP `scan_changes` | Architectural diff + impact analysis |
| Quick onboarding into unfamiliar code | MCP `get_context` | Compressed context tailored for token efficiency |
| Overview of the project structure | MCP `get_repo_map` | File tree + structural symbols |
| Check system health | MCP `watcher_status` | Embedder mode, LSP status |
| Find similar code / duplicates / alternative implementations | MCP `context_search` | Semantic search by selected code fragment |
| Search by code structure (not text) | MCP `structural_search` | 13 AST patterns (class_inheritance, decorator, async, etc.) |
| Complex multi-part questions | MCP `search_code(agentic=True)` | Auto-decomposes into sub-queries, searches, analyzes relations |
| Diagnose errors / check logs | MCP `get_logs` | Last errors and warnings from project logs |
| Check indexing progress | MCP `get_index_progress` | Progress of async indexing (phase, percent, files done/total) |

## Available MCP Tools (14 total)

| # | Tool | Purpose |
|---|---|---|
| 1 | `get_index_status` | Database state + chunk count |
| 2 | `index_project_dir` | Trigger full re-indexing |
| 3 | `search_code` | Semantic search by concept |
| 4 | `deep_search` | Iterative multi-pass search with query refinement |
| 5 | `cross_repo_search` | Multi-project search with @-mentions |
| 6 | `get_context` | Compressed multi-chunk context |
| 7 | `get_symbol_info` | Call graph + impact analysis |
| 8 | `get_repo_map` | Project structure + symbols |
| 9 | `scan_changes` | Architectural diff |
| 10 | `context_search` | Similar code by fragment |
| 11 | `structural_search` | AST pattern matching (13 patterns) |
| 12 | `watcher_status` | System health |
| 13 | `get_logs` | Recent errors from logs |
| 14 | `get_index_progress` | Indexing progress (phase, percent, files done/total) |

## AST Patterns (structural_search)

| Pattern | Use Case |
|---|---|
| `class_inheritance` | Find classes inheriting from Base |
| `class_with_decorator` | Find decorated classes |
| `function_with_decorator` | Find decorated functions (@app.get, etc.) |
| `async_function` | Find all async functions |
| `method_with_type_hints` | Methods with type annotations |
| `class_with_init` | Classes with __init__ |
| `import_from` | from X import Y statements |
| `try_except` | Error handling blocks |
| `list_comprehension` | List comprehensions |
| `dict_comprehension` | Dict comprehensions |
| `lambda` | Lambda functions |
| `with_statement` | Context managers |
| `comprehension` | Any comprehension |

## Mandatory Rules

**1. BEFORE editing any function or class — ALWAYS call `get_symbol_info`** to fully understand the impact of your changes on dependent modules and caller code.

**2. If `grep` yields no results — try `search_code`** (semantic search via the vector database).

**3. After `git pull` / `git checkout` — call `scan_changes`** to track file modifications made outside of Zed.

**4. No Blind Edits:** If `read_file` returns an Outline instead of the full text — you MUST first read the specific lines (`start_line`/`end_line`) you plan to modify. Never propose edits without seeing the up-to-date contents.

**5. Context Optimization:** Read code in targeted, small chunks (max 50 lines). Do not attempt to ingest entire files unless absolutely necessary.

**6. State Awareness:** The index now uses warmup on startup — 0 chunks means truly empty (first run). If empty, trigger `index_project_dir` and wait for completion before using `search_code`.

**7. Path Protocol:** Use native Windows paths (backslashes) when passing to MCP tools. Do NOT normalize to POSIX lowercase — our tools handle Windows paths natively.

**8. Post-Modification Sync:** After writing any file, call `index_project_dir(path)` + `get_index_status()` to verify cache state. Use `get_index_progress()` to monitor async indexing progress.

**9. Indexing Progress Awareness:** After `index_project_dir()`, indexing runs async. Use `get_index_progress()` to check status:
- phase="complete" → safe to use `search_code`
- phase="scanning" → wait or use `grep` as fallback
- percent < 50% → warn user indexing still in progress
- percent >= 80% → indexing almost done, results may be partial

**10. Complex Research:** Use `deep_search` for multi-step investigations. Use `cross_repo_search` with @-mentions for cross-project queries.

**11. Structural Analysis:** Use `structural_search` when you need code by structure (not text). 13 AST patterns available.

**12. Agentic Code Search:** Use `search_code(agentic=True)` or simply `search_code` for complex multi-part questions. Auto-decomposes query → parallel sub-searches → relation analysis → RRF aggregation. Based on arxiv.org/abs/2505.14321.

**13. MCP Quality over grep:** ALWAYS prefer MCP semantic tools (`search_code`, `deep_search`, `get_context`) over `grep`/`find_path` for code research. MCP tools find by concept/intent, not exact text — they catch relationships and context that grep misses. Use `grep` only for exact symbol names or when MCP index is empty.

**14. LanceDB Migration Safety:** NEVER call `drop_table` before data is fully validated in memory. Migration pattern: read → validate in memory → drop old → create new → insert. If validation fails, preserve original table. Always guard `chunk_index` against NaN/Float from Pandas with `pd.notna()` check.
