# Zed on Windows: Pitfalls and Architectural Decisions

[🇬🇧 English](ZED_WINDOWS_QUIRKS.md) • [🇷🇺 Русский](../ru/ZED_WINDOWS_QUIRKS.md) • [🇨🇳 中文](../zh/ZED_WINDOWS_QUIRKS.md)

> Version: 1.2 (2026-07-11) — updated for llama.cpp + Vulkan
> Applies to: MSCodeBase Intelligence v2.7.0+
> Detailed report: `investigations/LSP_WONTFIX.md`

## ⚠️ Critical: Restricted Mode

When opening a **new** project in Zed (one that hasn't been opened before), the editor
shows a **"Restricted Mode"** security dialog. This is NOT a bug — it's a built-in
Zed protection mechanism.

### What Restricted Mode blocks

| Mechanism | Status | Consequence |
|-----------|--------|-------------|
| Language servers (LSP) | 🔴 Fully blocked | `lsp_main.py` doesn't start → bridge doesn't write the bridge file |
| Local `settings.json` (`.zed/settings.json`) | 🔴 Ignored | `current_dir` and `env` from settings aren't applied |
| MCP servers | 🔴 Not installed | Context servers are not registered |

### How to fix

1. **Press "Trust and Continue"** (or `Enter`)
2. **Check "Trust all projects in D:\Project"** — so you won't
   see this dialog again for the entire workspace directory
3. **Without this checkbox**, every new project from `D:\Project` will
   show the dialog again

### Why MSCodeBase needs to know this

If the project is in Restricted Mode:
- `LSP Bridge` doesn't write JSON files → `resolve_project_root()` doesn't get
  the project from LSP
- `SQLite DB fallback` STILL WORKS (reads `workspaces` from Zed's database)
- But `settings.json` is ignored → `current_dir` doesn't change → CWD
  always points to the Zed installation directory (e.g., `D:\AI\Zed`
  or `C:\Program Files\Zed\`)

---

## 🪟 Windows Specifics: ZED_WORKTREE_ROOT

**Status:** ⚠️ Always `<unset>` on Windows (Zed bug #36019)

The `ZED_WORKTREE_ROOT` environment variable is NOT set on Windows.
This is a known Zed bug, closed without a fix.

### What this means

- In `settings.json` for `context_servers`, you cannot use `$ZED_WORKTREE_ROOT`
  in `current_dir` or `env`
- Any attempt to rely on this variable will result in `None`
- On Linux/macOS this variable is set correctly

### Solution in MSCodeBase

A fallback chain is used (see below) that works without
`ZED_WORKTREE_ROOT`:

1. ~~`LSP Bridge` — LSP gets `root_uri` through the LSP protocol~~
   **DOESN'T WORK on Windows** — LSP server doesn't start (see
   [`LSP_WONTFIX.md`](investigations/LSP_WONTFIX.md)).
2. `SQLite DB` — reads `workspaces` from Zed's database (primary working path)
3. `PROJECT_PATH` from `.env` — manual project specification

---

## 🔧 The resolve_project_root Chain (Priority)

The MCP server determines the current project in the following order:

```
[Request from tool]
    │
    ▼
1. Explicit project_root passed? ──(Yes)──> Use it
    │ (No)
    ▼
2. LSP Bridge file exists? ──(NO on Windows — LSP doesn't start)──> Step 3
3. SQLite Zed DB accessible? ──(Yes)──> Read workspaces,
    │                                  filter self-indexing,
    │                                  sort by .git + timestamp
    │ (No / DB locked)
    ▼
4. PROJECT_PATH from .env? ──(Yes)──> Use it
    │ (No)
    ▼
5. CWD (always Zed install dir, e.g. `D:\AI\Zed`) ──> self-indexing guard
    │                       ──> fallback to ext_root
    ▼
                ⚠️ Self-diagnosis mode
```

### Multi-window: MCP doesn't distinguish windows

**Problem:** All MCP tools (except `intel_*`) work with **a single project** —
the one that `resolve_project_root()` selected as default. If you have several
windows open with different projects, `get_index_status()` will show the default project's index,
not the window you're currently in.

**Why:** The MCP server is a single process for all Zed windows.
It doesn't know which window the request came from.
On macOS/Linux, `ZED_WORKTREE_ROOT` solves this problem,
on Windows it's always `<unset>`.

**Workaround:**
- For `intel_*` tools: they find the first non-self-indexing project on their own
- For `get_index_status`: close extra windows, keep only the desired project
- For `search_code`: pass an explicit `project_root` (if the tool supports it)

---

### Step 3: SQLite DB (Zed's database) — how it works

**This is NOT our database.** It's Zed's own database that stores
open projects (workspaces). We only read from it (read-only).
```
%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite
```

It reads the `workspaces` table:
```sql
SELECT paths, timestamp FROM workspaces ORDER BY timestamp DESC
```

**Important:** the column is named `paths`, not `absolute_path`.
The most recent workspace (by `timestamp`) is selected, which is not
self-indexing (rejected if the path matches the extension or Zed directory).

**Our database (LanceDB)** — vector code index, stored INSIDE the project:

| Project | Path to index |
|---------|---------------|
| `MSCodeBase` | `D:\Project\MSCodeBase\.codebase_indices\lancedb_v2\` |
| `gemma_agent` | `D:\Project\gemma_agent\.codebase_indices\lancedb_v2\` |

Each project has **its own isolated index**. When the extension is removed,
the index stays in the project. When the project is deleted — the index is lost.

**What else is stored in `.codebase_indices/`:** (inside the project)

| Directory | Purpose |
|-----------|---------|
| `lancedb_v2/` | LanceDB vector DB (code index: chunks + embeddings) |
| `branches/` | Git branches: isolated per-branch indices |
| `commit_memory/` | Commit history and semantic analysis |
| `intelligence/` | Project memory (ADR, known_issues, tech_debt) |

**Logs** (after v2.4.6): centralized in the extension directory, NOT in the project:
```
%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\
```

**Zed's database itself** (we only read):
```
%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite
```

**Self-indexing filtering:** paths matching `ext_root`, `Zed install dir`,
or system directories are discarded.

**Multi-window:** with multiple open windows, the project with the highest
score is selected (2 = has `.git`, 1 = no `.git`), then by most recent `updated_at`.

### Step 2: LSP Bridge — why it may be empty

```
🌉 BRIDGE: NO JSON FILES — LSP DIDN'T WRITE project_root!
  Reasons:
  1. Restricted Mode (didn't press "Trust and Continue")
  2. LSP crashes on startup (check: intel_get_runtime_status)
  3. Python files aren't open — LSP starts ONLY when
     a .py/.rs/... file is opened in the editor
```

---

## 📁 CWD = where Zed was launched from

**Important:** The CWD (working directory) of the MCP process is inherited from Zed itself.
On Windows, `current_dir` in `settings.json` doesn't resolve `$ZED_WORKTREE_ROOT`,
so the MCP server's CWD = Zed process's CWD.

If Zed was launched from:
- `cmd` or `powershell` → CWD will be the folder you launched from
- Shortcut / Start menu → CWD is typically the directory with `zed.exe`
- `D:\AI\Zed` (like yours) → CWD = `D:\AI\Zed`

---

## 🔒 Additional Zed Mechanisms

### Dynamic Sandbox

Zed launches MCP servers with restricted Windows permissions. If the process
requires elevated privileges (Win32 API, protected system folders),
the OS will return `Access Denied`.

**Solution:** The entire index is stored inside `.codebase_indices/` in the project root —
the process always has write permissions there.

### LSP Init Timeout (~10-15 seconds)

If `lsp_main.py` doesn't respond to `initialize` within 10-15 seconds, Zed
kills the LSP process and WILL NOT TRY TO RESTART IT until the window is reloaded.

**Solution:** LSP must return `READY` instantly (< 2 seconds).
Heavy work goes into a background thread.

### File Watcher Sensitivity

Zed locks open files with an exclusive lock. If a third-party process
(indexer, telemetry collector) modifies files in the workspace root too
aggressively, Zed may temporarily freeze its watchers.

**Solution:** Connection caching. Index files strictly in `.codebase_indices/`.

### Windows UNC Path Normalization

Windows paths may have a `\\?\` prefix (UNC). When comparing paths,
`D:\Project` and `\\?\D:\Project` are considered DIFFERENT strings, but
they point to the same directory.

**Solution:** Always use `Path(p).resolve()` when comparing paths.
This strips UNC prefixes.

---

## 📋 Setup Checklist on a New PC

1. ✅ Install the extension via `install.py`
2. ✅ Open ANY `.py` file in the project
3. ✅ Press "Trust and Continue" when the dialog appears
4. ✅ Check "Trust all projects in ..."
5. ✅ Check `intel_get_runtime_status` — project_path should be
   the path to the project, NOT to `ext_root`
6. If `project_path` shows ext_root — open a file and check step 3
7. ✅ Run `intel_get_telemetry` — verify data is being collected

---

## 📊 Troubleshooting

| Symptom | Look at | Command |
|---------|---------|---------|
| MCP doesn't know the project | Logs: `resolve_project_root: fallback to ext_root` | `intel_get_runtime_status` |
| LSP doesn't start | Logs: `BRIDGE: NO JSON FILES` | See "LSP doesn't start in Zed 1.9.0" section below |
| Index is empty | Status: 0 chunks | `get_index_status` |
| Tools not ready | Status: UNINITIALIZED | Open a file in the project |
| Database is locked | Logs: `database is locked` | Close other windows with the project |

---

## 🚫 LSP doesn't start in Zed 1.9.0 (WONTFIX)

**Status:** ⚠️ Known limitation of Zed 1.9.0 on Windows. Detailed report
with source code quotes: [`LSP_WONTFIX.md`](investigations/LSP_WONTFIX.md).

### What doesn't work

The LSP server `mscodebase-lsp` (Python, `src/lsp_main.py`, pygls-based) **cannot
be registered** through `settings.json`. Regardless of what
we write in `lsp.<id>.binary.path` or `languages.<lang>.language_servers`,
Zed cannot find an adapter named `mscodebase-lsp` in its `LanguageRegistry`
and crashes in `lsp_store.rs:start_language_server` with a panic
`expect("To find LSP adapter")`.

### The real reason (from Zed's source code)

From `crates/project/src/lsp_store.rs`:

```rust
let adapter = self.languages
    .lsp_adapters(language_name)
    .into_iter()
    .find(|adapter| adapter.name() == disposition.server_name)
    .expect("To find LSP adapter");
```

`lsp_adapters(name)` returns adapters only from:
1. **Built-in languages** — `crates/languages/src/*.rs` (Python, Rust, Go)
   with hardcoded LSP adapters.
2. **Loaded WASM extensions** — `extension.toml` + compiled
   `extension.wasm` with `impl zed::Extension::language_server_command`.

`lsp.<id>.binary.path` in `settings.json` is a **path override** for an already
registered adapter, not a registration of a new one. **This is by design, not a bug.**

### What this means for MSCodeBase

- **LSP features in the editor (inlay-hints, code-actions, autocomplete via
  mscodebase-lsp) are impossible on Zed 1.9.0 Windows.**
**All semantics and search continue to work through MCP** — 50 tools,
  filtering by `layer`, multi-granularity retrieval via
  `get_chunks_by_parent_id()`, telemetry, ETAPredictor. This is sufficient
  for 95% of code-assistant scenarios.
- **The LSP bridge (project_root from LSP)** remains empty, but `resolve_project_root()`
  compensates for this via the SQLite fallback.

### Why settings.json shows a Serde error

From `crates/settings_content/src/language.rs`:

```rust
#[schemars(range(min = 1, max = 128))]
pub tab_size: Option<NonZeroU32>,
```

The error `expected a nonzero u32` is **not about `language_servers`**, but about
`tab_size` (or another field with `NonZeroU32`) in the same struct. The parser
with `with_failible_options` resets this field to `None` and shows a
`Invalid user settings file` warning in the UI. **LSP doesn't crash because of this — it
doesn't even try to start because the adapter name isn't in the registry.**

### What to do

#### Now (release v2.4.4+)

1. **Don't register `mscodebase-lsp` in `settings.json`** — this creates
   false errors in the UI and provides nothing useful.
2. **Use MCP** for all operations — it doesn't depend on LSP.
3. **Check LSP state** via `scripts/check_lsp_health.py` —
   the script will write a clear report "LSP not registered / not starting"
   instead of uninformative Serde errors.

#### Future (v3.0+)

- **Write a Rust wrapper** (WASM via `wasm32-wasip2`) with
  `impl zed::Extension::language_server_command`, that calls
  `python -m src.lsp_main`. Install via `zed: install dev extension`.
  This is the only way to get LSP working in Zed.
- **Or replace `pyright`** via `lsp.pyright.binary.path` — minimal
  effort, but our LSP will masquerade as someone else's. Works for
  scenarios where in-editor highlighting is important, not adapter uniqueness.
