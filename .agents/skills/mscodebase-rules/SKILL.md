---
name: mscodebase-rules
description: "Tool selection rules for the Zed AI agent. Determines which tool to use depending on the task: grep, find_path, MCP search_code, get_symbol_info, get_context, get_repo_map, scan_changes."
---

# MSCodeBase Tool Selection Rules

## Tool Selection Matrix

| Scenario | Tool to Use | Rationale |
|---|---|---|
| Find a specific file by path or exact class/function name | `grep` / `find_path` | Instant, 100% exact match accuracy |
| Understand architecture, search by concept/intent, find relationships | MCP `search_code` | Semantic vector search connects abstract concepts |
| Rewrite a function and analyze what will break | MCP `get_symbol_info` (Call Graph) | Shows all dependent modules and inbound calls |
| Files created/deleted outside of Zed | MCP `scan_changes` | Architectural diff + impact analysis |
| Quick onboarding into unfamiliar code | MCP `get_context` | Compressed context tailored for token efficiency |
| Overview of the project structure | MCP `get_repo_map` | File tree + structural symbols |
| Check system health | MCP `watcher_status` | Embedder mode, LSP status |

## Mandatory Rules

**1. BEFORE editing any function or class — ALWAYS call `get_symbol_info`** to fully understand the impact of your changes on dependent modules and caller code.

**2. If `grep` yields no results — try `search_code`** (semantic search via the vector database).

**3. After `git pull` / `git checkout` — call `scan_changes`** to track file modifications made outside of Zed.

**4. No Blind Edits:** If `read_file` returns an Outline instead of the full text — you MUST first read the specific lines (`start_line`/`end_line`) you plan to modify. Never propose edits without seeing the up-to-date contents.

**5. Context Optimization:** Read code in targeted, small chunks (max 50 lines). Do not attempt to ingest entire files unless absolutely necessary.

**6. State Awareness:** If `get_index_status` returns 0 chunks — FORBIDDEN to use `search_code`. Switch to `grep` or `find_path` immediately.

**7. Path Normalization:** Always normalize paths to POSIX lowercase: `path.as_posix().lower()` before passing to tools.

**8. Post-Modification Sync:** After writing any file, call `index_project_dir(path)` + `get_index_status()` to verify cache state.
