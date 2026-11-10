# Configuration

> Rewritten 2026-11-08 against `src/config/settings.py`, `.env.example` and a live
> `get_config()` dump. Defaults shown are what the code returns **when nothing is
> set**. Numbers that change per repository (index size, timings) live in
> [FACTS.md](../FACTS.md), not here.

## 1. Where settings come from

1. Values are read from environment variables when the config object is built
   (`src/config/settings.py`, `get_config()`), so a change needs a **process restart**.
2. `.env` in the project root is loaded by `python-dotenv`; it is the intended place
   for local values. `.env.example` documents the supported surface.
3. Precedence: process environment > `.env` > built-in default.
4. Nothing in this list is read from a YAML/JSON config file — there is no second
   config format.

Groups below mirror the dataclasses: `server`, `search`, `embedding`, `index`,
`performance`, `security`, `memory`.

## 2. Server, profile and storage

| Variable | Default | Effect |
|---|---|---|
| `MSCODEBASE_MCP_PROFILE` | `core` | Tool surface: `core` = 17 tools, `full` = all 69 |
| `MSCODEBASE_MCP_TOOLS` | — | Explicit comma-separated allowlist; overrides the profile |
| `MSCODEBASE_EXECUTE_SCRIPT_ENABLED` | `false` | Registers `execute_script` (RCE on the host, off by default) |
| `MSCODEBASE_DATA_DIR` | `%LOCALAPPDATA%/mscodebase` (Windows) or `~/.cache/mscodebase` | Root for graph, memory, jobs, telemetry, commit memory |
| `MSCODEBASE_PROJECT_PATH` / `MSCODEBASE_PROJECT_ROOT` | unset | Pin the project when the host does not provide a workspace root |
| `MSCODEBASE_CHUNKS_DB` | `<project>/.mscodebase/chunks.db` | Override the SQLite chunk store location |
| `MSCODEBASE_LOG_DIR` | `<data_root>/logs` | Server log directory |
| `MSCODEBASE_LOCALE` | system / `en` | UI strings language (`en`, `ru`) |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8765` | Streamable-HTTP listener (stdio ignores it) |
| `LSP_HOST` / `MSCODEBASE_LSP_START_TIMEOUT` | `127.0.0.1` / — | basedpyright LSP client |

The per-project directory is `<data_root>/projects/<md5(project_path)[:8]>/`
(`src/core/artifact_paths.py`): `graph.db`, `intelligence/`, `commit_memory/`,
`telemetry/`. Only `chunks.db` and `.mscodebase/` live inside the project, and both
are gitignored.

## 3. Retrieval (the defaults that matter)

| Variable | Default | Effect |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | Skip dense/vector retrieval entirely; FTS5 + graph only |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | Use the SQLite/FTS5 chunk store for candidates |
| `MSCODEBASE_ONDEMAND_RERANK` | `false` | Re-score the top candidates with live embeddings when a provider exists; per-call override: `investigate(rerank=true)` |
| `MSCODEBASE_ONDEMAND_RERANK_TOP_N` | `10` | How many candidates enter the rerank pool |
| `MSCODEBASE_ONDEMAND_RERANK_MAX_CHARS` | `1600` | Text truncation before embedding |
| `MSCODEBASE_DOCS_MARGIN` | `4.0` | Docs channel wins when `docs_score − code_score > margin` |
| `MSCODEBASE_AUGMENT_CHUNKS` | `true` | Prepend `FILE:` / `SYMBOLS:` / `DOC:` to chunk text |
| `MSCODEBASE_CODE_BM25` (+`_K1`, `_B`, `_STOPWORDS`) | `false` / `1.2` / `0.45` / `true` | Identifier-aware BM25 scoring |
| `MSCODEBASE_RU_SYNONYMS` | `false` | Russian → English code-term expansion |
| `MSCODEBASE_DEMOTE_NON_CODE` / `_DEMOTE_INTENT_AWARE` | `false` | Down-rank docs/tests for code questions |
| `MSCODEBASE_P3_ANCHOR` | `false` | Module-head pool anchor |
| `MSCODEBASE_TESTS_SIGNAL` | `false` | Append covering tests to symbol results |
| `MSCODEBASE_LATE_ENRICHMENT` | `false` | Defer graph enrichment until after ranking |
| `MSCODEBASE_EVIDENCE_GATE` | `true` | Verify each `investigate` row (definition/ast/fresh/graph) and print a deterministic verdict; `0` restores the pre-gate answer |
| `MSCODEBASE_ASK_REWRITE` | `smart` | `on` — ask for an identifier whenever a Cyrillic question has no code token; `smart` — only when it also names a proper-noun-like Latin word (XERJ N03); `off` — return neighbours with a verdict. Measured: `experiments/xerj_2026_11/evidence_gate/REPORT_REWRITE.md` |
| `MSCODEBASE_SCRIPTS_DEMOTE` | `true` | Penalise `scripts/`, `examples/`, `benches/`, `fuzz/` rows for code questions, like tests and docs. Measured: XERJ P05 top-1 recovered, no `any` lost (`experiments/xerj_2026_11/probe_scripts_demote.py`) |

`EXPERIMENTS/**` is excluded from indexing by `FileGuard` regardless of these flags:
frozen panels must never appear as search hits.

## 4. Indexing and performance

| Variable | Default | Effect |
|---|---|---|
| `BASE_INDEX_DIR` | `.codebase_indices` | Legacy index directory name |
| `LANCEDB_VERSION` | `v2` | Vector-store layout (only used when dense is enabled) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `512` / `100` | Fallback line chunking |
| `INDEX_BATCH_SIZE` | `100` | Files per indexing batch |
| `MSCODEBASE_PARSE_TIMEOUT_SEC` | — | Per-file parse budget |
| `MSCODEBASE_LINK_TIMEOUT_SEC` | — | Graph link-pass budget |
| `MSCODEBASE_REINDEX_STALL_SEC` | — | Stall watchdog for long reindexes |
| `MSCODEBASE_IVF_MAX_ABANDONS` | — | Auto-disable IVF after N failed optimize/create |
| `MSCODEBASE_MAX_FILE_SIZE_MB` (security) | `10` | Files above this are skipped |

## 5. Providers (all optional)

Text-first search needs none of them; they are used for rerank, the legacy dense
path and LSP.

| Variable | Default | Effect |
|---|---|---|
| `LLAMA_CPP_ENABLED` | on unless `false` | Local llama.cpp server for embeddings/rerank |
| `LLAMA_CPP_PORT` / `RERANKER_PORT` | `8080` / `8081` | llama.cpp and BGE-M3 endpoints |
| `LM_STUDIO_HOST` / `LM_STUDIO_PORT` | `127.0.0.1` / `1234` | LM Studio provider |
| `OLLAMA_HOST` / `OLLAMA_PORT` | `127.0.0.1` / `11434` | Ollama provider |
| `EMBEDDING_MODEL` / `MODEL_NAME` / `EMBEDDING_DIMENSION` | `qwen3-embedding` / `multilingual-e5-small-int8` / `384` | Provider model selection |
| `MSCODEBASE_ONNX_PROVIDER` | — | Force a specific ONNX execution provider |
| `MSCODEBASE_REMOTE_TOKEN` / `_REMOTE_RATE_LIMIT_RPS` | — | Remote provider auth and rate limit |
| `MSCODEBASE_LANGUAGE_PACK` | `false` | Enable tree-sitter-language-pack (downloads parsers on first use) |

## 6. Safety and trust

| Variable | Default | Effect |
|---|---|---|
| `MSCODEBASE_TRUSTED_ROOTS` | project root | Paths tools may read/write |
| `MSCODEBASE_RESTRICTED_READ` | off | Restrict reads to trusted roots |
| `MSCODEBASE_SANDBOX_MODE` | off | Extra write restrictions |
| `MSCODEBASE_ALLOW_SELF_INDEX` | off | Allow indexing the server's own checkout (CI only) |
| `MSCODEBASE_ACK_SECRET` | derived | HMAC secret for `ack_impact` tokens |

Security details and the threat model: [SECURITY.md](SECURITY.md).

## 7. Hooks and gates

| Variable | Default | Effect |
|---|---|---|
| `MSCODEBASE_STALE_GATE` | `block` | `block` / `off` for the doc-drift gate in the OpenCode plugin |
| `MSCODEBASE_ISOLATION_GATE` | `advisory` | `advisory` / `block` / `off` for graph isolation |
| `MSCODEBASE_GATE_LOG` | `%TEMP%/opencode/mscodebase_gate.log` | Plugin log path |
| `MSCODEBASE_PY` | `<repo>/venv/Scripts/python.exe` | Interpreter the plugin calls |
| `MSCODEBASE_AUTODOC_LEDGERS` | off | Let AutoDocUpdater rewrite agent-owned registries |
| `MSCB_PRECOMMIT_FAST` / `MSCB_PRECOMMIT_GATE_TIMEOUT` | — / `900` | Pre-commit shortcuts and budget |

See [HOOKS_AND_GATES.md](HOOKS_AND_GATES.md) for what each gate checks.

## 8. How to verify a change

```bash
python -c "from src.config.settings import get_config; c=get_config(); print(c.search.dense_off, c.search.docs_margin)"
```

Config is built once per process: restart the MCP host after editing `.env`, then
`get_health_report()` should show the new values (or at least not the old provider
state).
