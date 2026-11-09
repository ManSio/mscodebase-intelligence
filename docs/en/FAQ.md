# FAQ — MSCodeBase Intelligence

[English](FAQ.md) · [Русский](../ru/FAQ.md) · [中文](../zh/FAQ.md)

Answers are read off the code in this repository (version 3.5.0), not off older
blog posts. Quotable numbers live in `docs/FACTS.md`.

---

## Does search need embeddings?

No, not by default. The default runtime is **text-first**:

| Setting | Default | Effect |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | no dense tier: the query is never embedded for vector search |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | chunks are text in SQLite FTS5, no vectors are stored |
| `MSCODEBASE_ONDEMAND_RERANK` | `false` | the top-N candidates are embedded live at query time when enabled **if** an embedder answers; per call: `investigate(rerank=true)` |

Candidates come from SQLite FTS5 (BM25 rank) plus the PropertyGraph. Indexing
also skips embeddings: `Indexer.index_project()` routes to
`_index_text_only_project()` when `dense_off` is true.

If no embedder is reachable, the on-demand rerank raises, is caught, and the
fused pool is returned in RRF order (`engine.py::_apply_ondemand_reranker_async`,
"Fallback к RRF-порядку"). Search still works — it just stops reordering by
cosine.

## Why do results look lexical?

Because they are lexical. With `dense_off=true` the candidate list is BM25 over
FTS5 plus graph hits; ranking is term-driven, so an exact identifier beats a
paraphrase. Two upgrades exist but are off by default and must be measured on
your own queries first: `MSCODEBASE_CODE_BM25=true` (identifier splitting,
field boosts) and `MSCODEBASE_RERANKER_*` providers. Quality figures per mode
are in `docs/FACTS.md` §5 — snapshots, not guarantees.

## Where does the data live?

Two locations, deliberately separated:

| What | Path |
|---|---|
| Chunk text + FTS5 index | `<project>/.mscodebase/chunks.db` (override: `MSCODEBASE_CHUNKS_DB`) |
| Graph, project memory, telemetry, LanceDB (only if used) | `<data_root>/projects/<hash8>/` |

`<data_root>` is `%LOCALAPPDATA%\mscodebase` on Windows,
`~/Library/Caches/mscodebase` on macOS, `~/.cache/mscodebase` on Linux.
Override with `MSCODEBASE_DATA_DIR` (`BASE_INDEX_DIR` is the legacy alias); a
project folder holds `graph.db`, `intelligence/project_memory.json`,
`metrics/job_history.json`, `commit_memory/`, `telemetry/YYYY-MM-DD.json`.

Artifacts were moved out of the indexed project on purpose: indexing someone
else's repository must not write into it. `chunks.db` is the exception and is
opt-out via `MSCODEBASE_CHUNKS_DB`.

## How do I see the other tools?

Registration and visibility are separate. **69** tools are always registered
(36 core + 16 intel + 13 inline + 4 dev). The surface is filtered by profile:

```bash
# default: 17 tools, one entry per intent
MSCODEBASE_MCP_PROFILE=core

# everything
MSCODEBASE_MCP_PROFILE=full
```

Restart the host after changing it — the filter runs once during
`create_mcp_server()`. `tool_help()` lists the active profile, the visible
tools and the hidden ones; it is always visible in the core profile.
`MSCODEBASE_MCP_TOOLS=a,b,c` is an explicit allowlist that overrides the
profile. `execute_script` is a separate optional 70th tool behind
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`.

## How do I reset the index?

Full profile: `intel_reset_index()` — closes DB handles, releases the PID lock,
deletes the index directory and legacy in-project dirs, then starts a background
reindex (poll `intel_get_job_status(job_id)`).

Core profile (no `intel_reset_index`): delete the artifacts and force a rebuild.

```powershell
Remove-Item .mscodebase\chunks.db* -Force
Remove-Item "$env:LOCALAPPDATA\mscodebase\projects\<hash8>" -Recurse -Force
```

Then re-index with `codebase(action="index", path="project_dir", project_root=".")`
(full profile: `intel_trigger_reindex()`), or from a shell:
`python scripts/reindex_text_only.py --project .` (text + graph, no embeddings);
`python scripts/rebuild_graph.py` rebuilds only the graph.

## "Nothing found" vs "empty index"

They are different states and the tools answer differently.

- **Empty index** — `codebase(action="index", path="status")` reports
  `total_chunks = 0`. This is not "no matches"; nothing has been indexed. Tools
  that check readiness raise `IndexNotReadyError`, which renders as
  `🟡 Warning: Index is not ready` with the detail
  `Index is empty for project: … Run index_project_dir() first.`
- **Reindex in progress** — the synchronous search path
  (`hybrid_search` / `search_with_mode`) returns an empty result immediately
  instead of waiting on DB locks; the async path raises with
  "⏳ Индекс перестраивается … повторите поисковый запрос через несколько секунд".
- **Genuinely no match** — `total_chunks > 0`, the query just has no lexical
  hit. Rephrase using identifiers that appear in the source, or add a
  `docs/`-intent query; static retrieval is not a paraphrase engine.

`investigate` shows the same distinction: it prints
"Ничего не найдено. Запрос не подтверждён ни одним каналом" only when all seven
channels came back empty, and appends `degraded: ...` when a channel timed out
instead.

## Can I run it without a GPU or without network?

Yes. Nothing in the default path needs a GPU, a cloud API, or internet: FTS5,
the AST graph, and tree-sitter parsing are all local. The only network use is
downloading optional models (GGUF/ONNX via `install.py`) and the optional
`tree-sitter-language-pack`, whose parsers are fetched on first use
(`MSCODEBASE_LANGUAGE_PACK=true`). With that flag off, every grammar comes from
a pinned wheel and no download happens.

Optional accelerators, all off by default: LM Studio (`127.0.0.1:1234`),
Ollama (`127.0.0.1:11434`), llama.cpp (`127.0.0.1:8080` embedder / `8081`
reranker), ONNX server (`127.0.0.1:1235`). See `LM_STUDIO_SETUP.md` and
`INSTALL_MODELS.md`.

## Host, logs, and after editing the server

**OpenCode is the primary host**: it launches
`…\Zed\extensions\mscodebase-intelligence\venv\Scripts\mscodebase-mcp.exe -u -m src.main`
with `PYTHONPATH` pointing at that extension directory. The Zed extension is
still supported (`extension.toml`, `capabilities = ["context_servers"]`). Both
run the copied code, so after editing `src/` run `python install.py --sync-only`
and restart the host — a reload is not enough, the process keeps old modules.

Logs: `<data_root>/logs/` (crash + rotation), `get_logs()` (this project's recent
warnings/errors), `debug_runtime_passport()` (full profile: RUN_ID, BUILD_ID, PID,
uptime, resolved project — tells you whether a restart actually happened).

Slow answers or one channel that always fails: check `get_health_report()`, then
`codebase(action="index", path="status")`, then `intel_get_runtime_status()`
(full profile). A single slow channel degrades `investigate` instead of failing
it; see `GRACEFUL_DEGRADATION.md` for what degrades and what fails.

See also `INSTALL.md`, `ARCHITECTURE.md`, `SEARCH_PIPELINE.md`,
`TELEMETRY.md`, and `docs/FACTS.md` for every quotable number.

**Verified against:** `pyproject.toml`, `src/config/settings.py`,
`src/core/search/engine.py`, `src/core/indexing/indexer.py`,
`src/core/indexing/chunk_store.py`, `src/core/artifact_paths.py`,
`src/core/intelligence/tools_reg.py`, `src/core/error_handler.py`,
`src/mcp/server_tools.py`, `src/mcp/tools/investigate_tool.py`,
`src/mcp/tools/codebase_tool.py`, `install.py`, `extension.toml`,
`scripts/reindex_text_only.py`, `%USERPROFILE%\.config\opencode\opencode.jsonc`.
