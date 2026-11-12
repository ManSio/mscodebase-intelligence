# Where MSCodeBase puts data

> Written 2026-11-12 and verified against `install.py` v3.2,
> `src/core/artifact_paths.py`, `src/core/artifact_gc.py`,
> `src/core/log_manager.py`, `src/sources/git_url/__init__.py` and a live
> `install.py --doctor` run. Numbers are measured, not estimated.

One question this page answers: *what did the installer and the server create on
my disk, who owns each path, and how do I get rid of it?*

```bash
python install.py --doctor              # what is installed and how much it weighs
python install.py --clean --dry-run     # paths and sizes; deletes nothing
python install.py --clean --yes         # delete every layer below
```

## 1. The four layers

| Layer | Path (default) | Created by | What it is |
|---|---|---|---|
| **Install root** | Windows `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`; macOS `~/Library/Application Support/Zed/extensions/…`; Linux `~/.local/share/zed/extensions/…` | `install.py` steps `step_copy`, `step_venv`, `step_pip`, `step_llama`, `step_gguf`, `step_models`, `step_uninst` | The installed copy: code, `venv/`, optional models, uninstaller |
| **Data root** | `%LOCALAPPDATA%\mscodebase` (Win) · `$XDG_CACHE_HOME/mscodebase` or `~/.cache/mscodebase` (POSIX) | `src/core/artifact_paths.py::get_data_root` | Per-project caches, logs, shared models, repo clones |
| **Project artifacts** | `<project>/.mscodebase/chunks.db` | server (`MSCODEBASE_SQLITE_CHUNKS`) | FTS5 text index for that project |
| **Host config** | Zed: `%APPDATA%\Zed\settings.json` (`context_servers`) | `install.py` step `step_zedcfg` → `adapters/zed/zed_config.py` | One entry telling the host how to launch the server |

Both roots are relocatable: `MSCODEBASE_INSTALL_ROOT` and `MSCODEBASE_DATA_DIR`
(`BASE_INDEX_DIR` is still accepted as a legacy alias for the second).

## 2. Install root — what is inside

| Path | Owner | Purpose | Size |
|---|---|---|---|
| `src/`, `scripts/`, `adapters/`, `locales/`, `docs/` | `step_copy` (`_sync_dir`) | Executable copy of the repository (without `experiments/`) | a few MB |
| `venv/` | `step_venv`, `step_pip` | Python environment with pinned dependencies | ~1 GB |
| `venv/Scripts/mscodebase-mcp.exe` | `pip` entry point (`pyproject.toml [project.scripts]`) | The stdio command hosts launch | — |
| `.codebase_models/onnx/…` | `step_models` (only with `--with-models`) | ONNX embedder + reranker | ~657 MB |
| `llama_msvc/` | `step_llama` | llama-server binary for the GGUF path | ~200 MB |
| `models/*.gguf` | `step_gguf` (only with `--with-models`) | GGUF embedder + reranker | ~700 MB |
| `uninstall.bat` / `uninstall.sh` | `step_uninst` (`_build_uninstaller`) | Kills the server and removes this directory | < 1 KB |
| `__mscodebase_ext__.marker` | `step_copy` | Tells `src/main.py` it runs from an installed copy | < 1 KB |

Measured on the development machine (2026-11-12, models installed):
**3.0 GB over 28 429 files**, of which `venv/` plus models make up almost all of it.

## 3. Data root — what is inside

| Path | Owner | Purpose | Policy |
|---|---|---|---|
| `projects/<hash8>/graph.db` | `artifact_paths.get_graph_db_path` | PropertyGraph: files, symbols, calls, imports | deleted with the project dir |
| `projects/<hash8>/lancedb_v2/` | `get_index_dir`, `get_db_path` | Vector index (only when dense is enabled) | same |
| `projects/<hash8>/intelligence/` | `get_intelligence_dir` | Project memory: ADRs, incidents, debt | same |
| `projects/<hash8>/metrics/` | `get_metrics_dir` | Indexing job history (ETA model) | same |
| `projects/<hash8>/commit_memory/` | `get_commit_memory_dir` | Semantic commit cache | same |
| `projects/<hash8>/branches/` | `get_branches_dir` | Per-branch index state | same |
| `projects/<hash8>/telemetry/` | `get_telemetry_dir` | Daily JSON snapshots | files older than **90 days** pruned |
| `projects/<hash8>/summaries_cache/` | `get_summaries_cache_dir` | LLM chunk summaries | same as project dir |
| `projects/<hash8>/progress.json` | `get_progress_file` | Indexing progress contract | overwritten |
| `projects/<hash8>/action_receipts.jsonl` | `src/core/action_receipt.py` | Receipts for write actions | verified 60 d / inconclusive 7 d (`purge`) |
| `logs/mscodebase-intelligence.log` | `log_manager.get_main_log_path` | Server log | rotates at 2 MB × 3 files, deleted after **7 days** |
| `logs/crash.json` | `get_crash_log_path` | Last resource-monitor crash | overwritten |
| `models/.codebase_models/onnx/…` | `get_onnx_models_base` | Shared copy of downloaded models | only `--clean` |
| `repos/<hash8>/` | `get_repos_cache_dir` | Clones of remote repositories | LRU(5) + TTL 24 h (`src/sources/git_url`) |
| `projects/<hash8>/` (whole dir) | — | — | inactive dirs older than **30 days** and empty dirs are pruned by `artifact_gc.prune_stale_artifacts()` |

Measured on the development machine (2026-11-12): **302.9 MB over 2 934 files**.
`--doctor` in a real project directory that also holds `chunks.db` (78 MB) and a
local model copy (960 MB) reported **4.3 GB over 31 385 files** across all layers.

## 4. Project artifacts

| Path | Owner | Purpose |
|---|---|---|
| `<project>/.mscodebase/chunks.db` | `MSCODEBASE_SQLITE_CHUNKS` storage | Text index (FTS5/BM25) used by the default search path; `--doctor` reports its chunk count |
| `<project>/.codebase_indices/`, `.codebase/`, `.mscodebase/telemetry/` | legacy | Moved into the data root on first project open (`artifact_paths.migrate_legacy_artifacts`) |
| `<project>/.codebase_models/` | `scripts/download_model.py` (download staging) | Temporary copy before the model is installed under the install root |

`experiments/**` is excluded from indexing by design, so it never grows the index.

## 5. Policies

- **Models are opt-in.** `install.py` is text-first: without `--with-models` it
  performs no model download and writes no model directory. `--skip-models` and
  `--no-models` are still accepted for old scripts.
- **Logs** rotate by size (2 MB, 3 files) and are pruned after 7 days
  (`log_manager._MAX_LOG_BYTES`, `_MAX_LOG_FILES`, `_LOG_RETENTION_DAYS`).
- **Telemetry** snapshots are pruned after 90 days; **inactive project dirs**
  after 30 days (`artifact_gc.DEFAULT_*`); empty project dirs are removed at once.
- **Repo clones** are an LRU of 5 with a 24 h TTL, plus a 500 MB post-clone size
  cap (`git_url.DEFAULT_MAX_CLONE_BYTES`).
- **Shared model cache** (`data_root/models`) has no TTL: models are removed only
  by `install.py --clean`.
- **Uninstall** is `install.py --clean --yes`, which removes all four layers
  except the host config entry (delete the `mscodebase` entry from
  `settings.json` / `opencode.json` / `.mcp.json` yourself, or run
  `install.py --no-zed` and never create it).

## 6. Reading the doctor output

```
+ install_root              3.0 GB  28429 file(s)  C:\Users\<user>\AppData\Local\Zed\extensions\mscodebase-intelligence
+ data_root               302.9 MB   2934 file(s)  C:\Users\<user>\AppData\Local\mscodebase
+ project_chunks           78.0 MB      4 file(s)  D:\work\repo\.mscodebase
   ...

index           7278 chunk(s)  (D:\work\repo\.mscodebase\chunks.db)
total           4.3 GB over 31385 file(s)
```

`+` exists, `-` absent. `index missing` means the text index for the current
directory was never built (the first `codebase(action="index")` call builds it),
not that search is broken. `--json` prints the same data for scripts.
