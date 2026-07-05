# MSCodeBase Intelligence — AI Usage Guide (Hybrid MCP + LSP)

> Global instruction for AI assistants working inside Zed with the MSCodeBase Intelligence extension.
>
> Architecture:
> - Hybrid LSP + MCP
> - Multi-Window Registry
> - Background Indexing
> - Semantic Search
> - Project Memory
> - Intel Layer

---

# 1. PRIMARY EXECUTION MODEL

Always work in this order:

```
Runtime
   ↓
Project Context
   ↓
Index State
   ↓
Memory
   ↓
Search
   ↓
Read
   ↓
Modify
   ↓
notify_change()
```

Never skip steps.

---

# 2. SESSION INITIALIZATION (MANDATORY)

At the beginning of EVERY task:

1.

```
intel_get_runtime_status
```

Verify:

- Runtime ready
- Bridge connected
- Registry active
- MCP healthy

If runtime is unavailable:

- Stop using MCP
- Switch to native Zed tools
- Continue using grep/read_file/terminal only

---

2.

```
intel_get_project_memory
```

Read:

- ADR
- previous fixes
- known bugs
- failed attempts

Never repeat already failed approaches.

---

3.

```
get_index_status
```

Determine current index state.

---

# 3. INDEX STATE RULES

If

```
total_chunks == 0
```

Semantic search is FORBIDDEN.

Use:

- grep
- read_file
- terminal

Suggest:

```
intel_trigger_reindex
```

instead of blocking indexing.

---

If

```
total_chunks > 0
```

Semantic tools become available.

---

# 4. PROJECT CONTEXT RULES

MSCodeBase uses Hybrid LSP + MCP.

Important:

MCP DOES NOT know current project by itself.

Project context comes from

LSP
↓

Bridge
↓

ProjectIndexerRegistry
↓

MCP

Therefore NEVER assume project context.

Always trust:

- intel_get_runtime_status
- Registry
- Bridge

Never invent paths.

---

# 5. MULTI-WINDOW RULES

Multiple Zed windows may be opened simultaneously.

Never assume only one project exists.

Registry selects project.

Never cache project path manually.

Never hardcode workspace path.

Always resolve project through Registry.

---

# 6. MCP STARTUP RULES

Immediately after:

- switching projects
- opening workspace
- restarting extension

the MCP server may still be starting.

During startup:

- Registry may be empty
- Index may be unavailable
- Bridge may still synchronize

If runtime reports:

- starting
- initializing
- registry loading

DO NOT report bugs.

Instead:

Wait until runtime becomes Ready.

Only then execute semantic tools.

---

# 7. REINDEX RULES

Never call old blocking

```
index_project_dir
```

Preferred:

```
intel_trigger_reindex
```

Immediately return control to user.

Poll progress using

```
intel_get_job_status
```

Never block UI.

---

# 8. SEARCH TOOL SELECTION

Simple filename?

↓

grep

Need semantics?

↓

search_code

Need architecture?

↓

intel_code_topology

Need exact symbol?

↓

get_symbol_info

Need impact?

↓

impact_analysis

Need AST?

↓

structural_search

Need bug history?

↓

get_bug_correlation

Need commits?

↓

get_file_history

Need runtime crash analysis?

↓

intel_predict_root_cause

Need logs?

↓

get_logs

---

# 9. SEARCH MODES

search_code(mode)

fast

Exact/simple search

quality

Default

Architecture

Logic

deep

Large investigation

Cross-module reasoning

context

Code similarity

auto

Automatic selection

---

# 10. READING RULES

Maximum:

50 lines

per read.

Never ingest huge files.

Navigate surgically.

---

# 11. SAFE WRITING

Before editing:

Read target lines again.

After editing:

notify_change()

Immediately verify:

get_index_status()

If bug fixed:

intel_log_incident()

---

# 12. MEMORY RULES

Every completed task should produce knowledge.

Use

```
intel_log_incident
```

Include:

Problem

Cause

Solution

Lessons

Affected files

---

# 13. SELF-CHECK BEFORE ANSWER

Before saying

"Done"

verify:

Runtime healthy

Correct project

Correct index

No transport errors

No stale Registry

No empty semantic search

If uncertain:

Run

```
intel_get_runtime_status
```

again.

---

# 14. PROCESS CONSISTENCY

Remember:

The running MCP process may NOT be the latest code.

If behavior contradicts source code:

Suspect:

- stale process
- stale environment
- old Registry
- old Bridge
- old extension instance

Do NOT immediately conclude the code is wrong.

Always compare:

Runtime

↓

Source

↓

Configuration

↓

Environment

Only then diagnose.

---

# 15. PROJECT PATH RULES

Never assume:

Current Working Directory

Current executable path

Extension installation path

are equal to

Project Root.

They are different concepts.

Definitions:

PROJECT ROOT

The user workspace.

EXTENSION ROOT

Installed extension directory.

ZED INSTALL

Editor installation.

These must never be confused.

---

# 16. SELF-INDEXING RULES

Self-indexing protection exists ONLY to prevent indexing:

- installed extension
- Zed installation
- extension runtime

It MUST NOT block:

Developer repository.

If

PROJECT_ROOT

!=

EXTENSION_ROOT

the repository is valid.

Never diagnose self-indexing before verifying these paths.

---

# 17. BRIDGE RULES

Bridge is authoritative.

Never reconstruct project state yourself.

Bridge may temporarily lag during startup.

If Bridge has not synchronized yet:

Wait.

Do not rewrite architecture.

---

# 18. WINDOWS PATHS

Always use native Windows paths.

Correct:

```
src\\core\\indexer.py
```

Absolute:

```
D:\\Project\\MSCodeBase\\src\\core\\indexer.py
```

Never use Linux separators.

Never pass environment variables as file paths.

Incorrect:

```
$ZED_WORKTREE_ROOT\\src...
```

Correct:

resolved path only.

---

# 19. FORBIDDEN

Never:

❌ guess line numbers

❌ read huge files

❌ retry identical failing tool calls

❌ invent architecture

❌ bypass Registry

❌ bypass Bridge

❌ hardcode project path

❌ assume single-window mode

❌ print debug output to stdout

❌ break JSON-RPC

---

# 20. FALLBACK STRATEGY

If MCP becomes unavailable:

Immediately switch to:

- grep
- terminal
- read_file

Continue solving task.

Do not repeatedly retry broken MCP calls.

---

# 21. ARCHITECTURE SUMMARY

Current production architecture:

```
          Zed

     +-------------+
     |     LSP     |
     +-------------+
            │
            ▼
    LSP Project Bridge
            │
            ▼
ProjectIndexerRegistry
            │
            ▼
      MCP Server
            │
            ▼
  Intel + Search + Memory
            │
            ▼
       LanceDB Index
```

Project context always flows from LSP to MCP through the Bridge.

Never assume MCP knows the project independently.

---

# 22. FINAL RULE

If there is any contradiction between:

- source code
- runtime
- configuration
- registry
- bridge

Do not guess.

Investigate until the contradiction is resolved.

Evidence always has priority over assumptions.
