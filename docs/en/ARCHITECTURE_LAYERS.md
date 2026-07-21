# Architecture Layers — MSCodeBase Intelligence

[🇬🇧 English](ARCHITECTURE_LAYERS.md) • [🇷🇺 Русский](../ru/ARCHITECTURE_LAYERS.md) • [🇨🇳 中文](../zh/ARCHITECTURE_LAYERS.md)

Each layer answers exactly one question.

```
 Layer 0: Filesystem        — what files exist on disk?
 Layer 1: SystemArtifacts   — is this a system path?
 Layer 2: Bridge            — which project did LSP report?
 Layer 3: Registry          — which Indexer owns this project?
 Layer 4: StateMachine      — what state is the project in?
 Layer 5: RuntimeCoordinator — can the request be executed?
 Layer 6: ProjectContext    — what does the project look like right now?
 Layer 7: Passport          — which process is currently running?
 Layer 8: Graph (v3.0)      — PropertyGraph: SQLite nodes/edges/cypher?
 Layer 9: Intel Layer       — what to do with this information?
 Layer 10: AI Agent         — response to the user
```

> **v3.0 change:** Layer 8 (Graph) added between Passport and Intel. PropertyGraph
> stores typed nodes (15 labels) and edges (27 types) in `.codebase/graph.db` (SQLite WAL+mmap).

---

## Layer 0 — Filesystem

**Question:** what files exist on disk?
**Code:** `os.walk`, `Path.rglob`, `FileGuard`
**Does not know:** about indexes, MCP, or LSP.

---

## Layer 1 — SystemArtifacts

**Question:** is this a system path?
**Code:** `SystemArtifacts.is_system_path()`
**Does not know:** about Registry, Bridge, Runtime, or Indexer.

4 sub-layers of protection:
1. **Directory Guard** — `.mscodebase/`, `.codebase_indices/`, `.git/`, `node_modules/`
2. **Artifact Guard** — `chunk_summaries.json`, `incidents.json`, `project_memory.json`
3. **Feedback Guard** — files created by the indexer itself
4. **Embedding Guard** — final check before embedding

**Rule:** any file inside `.mscodebase/` or `.codebase_indices/` = NOT indexed.

---

## Layer 2 — Bridge (LSP→MCP)

**Question:** which project did LSP report?
**Code:** `read_project_from_bridge()`, `write_active_project()`
**Does not know:** about indexes or Runtime.

Bridge — a temporary file (~/.mscodebase/bridge/session_*.json)
that LSP writes on each didOpen/didSave. MCP reads it
when it needs to determine project_root.

---

## Layer 3 — Registry (ProjectIndexerRegistry)

**Question:** which Indexer belongs to this project?
**Code:** `ProjectIndexerRegistry.get_indexer(path)`
**Does not know:** about MCP, Bridge, or Runtime.

Per-project singleton Indexers with LRU eviction (max 5).
Each project has its own Lock for LanceDB.

---

## Layer 4 — StateMachine

**Question:** what state is the project in?
**Code:** `ProjectIndexerRegistry.get_state()`, `wait_until_ready()`
**Does not know:** about Bridge or MCP requests.

```
UNINITIALIZED → STARTING → INDEXING → READY → FAILED
```

---

## Layer 5 — RuntimeCoordinator

**Question:** can the MCP request be executed?
**Code:** `RuntimeCoordinator.can_execute()`
**Does not know:** about code structure or search.

Uses:
- SystemArtifacts (Layer 1) — is the path non-system?
- Bridge (Layer 2) — is LSP synchronized?
- Registry + StateMachine (Layer 3-4) — is the project ready?

Returns `ExecutionVerdict`:
- `ok` — can execute
- `reason` — the reason (ready / system_path / project_not_ready / ...)
- `retry_after` — retry interval
- `requires_reindex` — needs reindexing
- `warnings` — warnings

---

## Layer 6 — ProjectContext

**Question:** what does the project look like right now?
**Code:** `ProjectContext.capture()`
**Does not know:** about MCP requests, does not start operations.

Returns Snapshot:
- state, index (chunks/files/symbols), bridge, runtime (PID/uptime),
  health (warnings/errors), memory (incidents/ADRs), jobs

---

## Layer 7 — Passport

**Question:** which process is currently running?
**Code:** `debug_runtime_passport()` — MCP tool
**Does not know:** about index state.

Shows: RUN_ID, BUILD_ID, PID, uptime, ext_root, project_root,
env (PROJECT_PATH, ZED_WORKTREE_ROOT, PYTHONPATH), guard result.

---

## Layer 8 — Intel Layer

**Question:** what to do with the information?
**Code:** `intel_get_runtime_status`, `intel_get_project_context`,
         `intel_explain_project_state`, `intel_predict_root_cause`
**Does not know:** about low-level details.

Aggregates data from lower layers into ready-made answers.

---

## Layer 9 — AI Agent

**Question:** what response to give the user?
**Code:** rule system (AGENTS.md, SKILL.md)
**Does not know:** about internal architecture.

---

### 🔗 Related Documents

| Document | Description |
|----------|----------|
| [README.md](../README.md) | Main documentation, map of all docs |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Project architecture, DI, layers |
| [TELEMETRY.md](TELEMETRY.md) | Metrics and telemetry |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
