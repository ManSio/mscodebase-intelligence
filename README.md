<div align="center">

<img src="logo/baner.png" alt="MSCodeBase Banner" width="100%"/>

[English](README.md) · [Русский](docs/ru/README.md) · [中文](docs/zh/README.md)

# MSCodebase Intelligence

**Local-first code intelligence for Zed: lexical search, call graph, impact analysis, project memory, and safe write tools — exposed over MCP.**

[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Zed](https://img.shields.io/badge/Zed-extension-orange.svg)](https://zed.dev/)
[![CI](https://github.com/ManSio/mscodebase-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/ManSio/mscodebase-intelligence/actions/workflows/ci.yml)

*Last updated: 2026-10-25. The English page is authoritative; RU/ZH mirrors may lag.*

</div>

---

## What this is

MSCodebase Intelligence is a **local MCP server** that gives an AI assistant
working in Zed a grounded view of a codebase. It is deliberately not a chat
model and not a replacement for the editor's LSP. Its job is to answer:

- Where is this symbol defined, who calls it, and what breaks if it changes?
- Which files are relevant to this question — in code, tests, or documentation?
- What did the project already decide, and which incidents are still open?
- Can a rename/move/replace be previewed and applied safely?

The current default is **text-first retrieval**: SQLite FTS5/BM25 plus a
Tree-sitter/PropertyGraph index. Embedding and reranker providers exist, but
they are optional and are not required for the default path. This choice is
intentional: it keeps the server useful offline, keeps latency predictable, and
avoids making a vector database the single point of failure.

## What works today

| Area | What it does | Notes |
|---|---|---|
| Code search | BM25/FTS5 over parsed chunks; exact-symbol and path signals; optional graph expansion | `search_code` |
| Documentation search | Separate `docs/**` FTS channel, automatically selected when the BM25 margin is strong | No LLM router |
| Symbol intelligence | Definition, callers/callees, references, impact, structural search | `get_symbol_info`, `impact_analysis`, `structural_search` |
| Graph | PropertyGraph of files/symbols with call, import, assignment, decorator and override edges | Rebuild with `scripts/rebuild_graph.py` if empty |
| Project memory | ADRs, incidents, known issues, retraction/supersede lifecycle | `intel_*` tools |
| Safe writes | Rename, move, delete, replace, insert with preview/impact checks | `codebase(action=...)` |
| Diagnostics | Runtime passport, health report, index status, logs, job status | `debug_runtime_passport`, `get_health_report` |
| LSP rename | Basedpyright-backed cross-file rename with SymbolIndex fallback | Only for rename |

## Search quality: measured, with its limits

Quality claims are only useful with the measuring stick attached. The numbers
below come from an internal **48-query panel** (33 real project questions plus
15 docstring-derived questions), evaluated on a **clean index** with
`experiments/**` excluded and the graph present. They are not a universal
benchmark, and they do not describe every language or repository.

| Path | hit@1 | hit@5 | What the number means |
|---|---:|---:|---|
| Code, quality mode | 0.825 | 0.900 | 33/40 code questions returned the correct file first |
| Docs, exact path | 0.000 | 0.125 | Gold points at `docs/en/X`; retrieval often returns `docs/ru/X` |
| Docs, same basename | 0.750 | 0.750 | Counting translations as the same document |
| Overall, quality mode | 0.688 | 0.750 | Code and docs mixed exactly as the panel is labeled |
| Overall, auto docs route | 0.792 | 0.875 | BM25-margin router + docs channel; translations normalized |
| Fast mode | 0.542 | 0.729 | Lower quality, lower latency; use for exact/simple lookups |

What this does **not** mean:

- It does **not** mean 95% accuracy. No static retrieval setup on this panel
  reached that. A two-channel repo map (code PageRank + docs BM25) reached about
  40% / 62% / 73% gold-file coverage at 1k / 2k / 4k tokens with perfect routing;
  PageRank alone was lower (about 33% / 55% / 68% on code queries). It is a
  context-selection aid, not a search replacement.
- It does **not** mean every reranker improves things. Several local rerankers
  were measured and rejected because they lowered hit@1 or added unacceptable
  latency on this panel.
- It does **not** mean the docs path is broken. The docs channel often returns
  the correct document in another language (`docs/ru/X` for `docs/en/X`). That
  is a gold-labeling issue, not a retrieval failure.

The panel, raw runs, hypotheses and summaries live under `experiments/`. Treat
them as a reproducible lab notebook, not as marketing copy.

## How search works

The default path is deterministic:

1. **Parse and index** files into chunks and a PropertyGraph.
2. **Retrieve** candidates with SQLite FTS5/BM25, symbol/path signals, and
   optionally graph neighbours.
3. **Rank and clean** the candidates: optional on-demand rerank, exact-name
   boost, and symbol deduplication. RRF/MMR/dense fusion belong to the optional
   LanceDB/vector path, not to every default query.
4. **Route docs cheaply** when the best docs score exceeds the best code score
   by a configurable margin (`MSCODEBASE_DOCS_MARGIN`, default `4.0`).
5. **Return** ranked chunks/files with metadata. `intent="docs"` or
   `intent="code"` overrides the automatic choice.

There is no LLM in this routing step. The router is one extra FTS query and a
score comparison, which keeps it local, explainable and cheap.

Optional layers:

- Embedding providers (llama.cpp GGUF, ONNX, LM Studio/Ollama) for vector
  candidates.
- On-demand reranking when a provider is configured.
- Graph expansion and PageRank-style repository ranking.

When `MSCODEBASE_DENSE_OFF=true` (the current default), the server does not
require an embedding server to answer code or docs queries.

## Quick start

Requirements: Windows is the validated platform; Python 3.14+; Zed with the
`mscodebase-intelligence` extension installed.

```bash
cd <repo-root>
python install.py
# or, for a code-only sync without prompts:
python install.py --sync
# CI-style, no prompts:
python install.py --yes
```

`install.py` copies the server into the Zed extension directory, installs
dependencies, optionally prepares model binaries, and writes the MCP
configuration. Restart Zed after it finishes.

Verify from the agent panel:

```text
debug_runtime_passport()
intel_get_runtime_status()
codebase(action="index", path="status")
```

If the graph is empty but chunks exist, rebuild only the graph (no vectors):

```bash
python scripts/rebuild_graph.py
```

If the index is stale or missing, rebuild text chunks and graph:

```bash
python scripts/reindex_text_only.py --project .
```

Then restart the MCP server/Zed so the new process opens the rebuilt stores.

## Tools

The server registers **64 tools** in four groups; `execute_script` adds one
optional tool when `MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`. The default
allowlist exposes **49** of them; hidden tools can be enabled with
`MSCODEBASE_MCP_TOOLS` (empty string shows all). The exact visible set is
reported in the MCP startup log and by `intel_get_runtime_status`.

| Group | Examples | Purpose |
|---|---|---|
| Search and analysis | `search_code`, `plan_search`, `get_symbol_info`, `impact_analysis`, `structural_search`, `graph_query` | Find code, symbols, relationships, and change impact |
| Index and system | `codebase(action="index"...)`, `notify_change`, `read_live_file`, `get_health_report`, `get_logs` | Keep the index fresh and diagnose it |
| Intelligence | `intel_get_runtime_status`, `intel_get_project_memory`, `intel_log_incident`, `intel_analyze_incident`, `intel_predict_root_cause` | Project memory, incidents, runtime state |
| Write and lifecycle | `codebase(action="rename"...)`, `move`, `safe_delete`, `replace`, `insert_before/after`, `ack_impact` | Preview and apply safe source changes |
| Dev | `bump_version`, `auto_update_docs`, `install_git_hooks`, `generate_docs` | Repository maintenance |

The `codebase` tool is a hub: its `action` selects index, git, or write
operations. See the tool schema in the MCP client rather than relying on a
hand-written list that can drift.

## Architecture

```text
Zed
 │
 ├── built-in LSP (autocomplete, diagnostics)
 │
 └── MCP client
      │
      ▼
 MSCodebase MCP server
   ├── Search      SQLite FTS5/BM25, symbol and path signals, optional graph
   ├── Graph       PropertyGraph: calls, imports, assignments, decorators, overrides
   ├── Index       parser → chunks → FTS5 + graph; freshness checks
   ├── Memory      ADRs, incidents, known issues, retract/supersede
   ├── Writes      rename/move/delete/replace/insert with impact guards
   ├── Diagnostics runtime passport, health, jobs, logs, telemetry
   └── Optional    embedding providers, reranker, LSP rename
```

The canonical data locations are outside the repository:

- `%LOCALAPPDATA%/mscodebase/projects/<hash>/` — per-project graph, memory,
  job state.
- `%LOCALAPPDATA%/mscodebase/logs/` — server logs.
- `<project>/.mscodebase/chunks.db` — text chunk store used by the Phase 3
  search path.

LanceDB remains part of the legacy/optional vector path; it is not required by
the default text-first configuration.

## Configuration

All settings are environment variables with defaults in
`src/config/settings.py`. The ones that matter most for search:

| Variable | Default | Effect |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | Skip dense/vector retrieval; use FTS5, symbols, graph |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | Use the SQLite/FTS5 chunk store |
| `MSCODEBASE_DEMOTE_NON_CODE` | `false` | Down-weight tests/docs/experiments in the fused pool |
| `MSCODEBASE_DEMOTE_INTENT_AWARE` | `false` | Keep docs when the query is classified as docs |
| `MSCODEBASE_DOCS_MARGIN` | `4.0` | Auto docs routing threshold (docs score − code score) |
| `MSCODEBASE_ONDEMAND_RERANK` | `true` | Optional live rerank; requires a provider |
| `MSCODEBASE_P3_ANCHOR` | `false` | Module-head anchors; measured to add latency without a reranker |
| `MSCODEBASE_MCP_TOOLS` | default set | Tool allowlist; empty means all registered tools |

`experiments/**` is intentionally excluded from indexing. It contains frozen
panels and run artifacts; indexing them previously made BM25 return the panel
itself instead of the code. The files remain tracked in git.

## Supported languages

Python is the primary, fully exercised language. Tree-sitter parsing covers
JavaScript, TypeScript/TSX, Rust, Go, Java, C#, Ruby, PHP, Kotlin, Swift, C,
C++, Scala and Dart. SQL, YAML, TOML, HTML, CSS and HCL/Terraform are indexed
as context, without the same call-graph coverage. Graph and data-flow depth
depend on the grammar; not every language exposes the same edge types.

## Limitations and known issues

These are deliberate, documented boundaries rather than hidden behavior:

- **Docs gold vs language:** the docs channel may return `docs/ru/X.md` when
  the evaluation gold is `docs/en/X.md`. The document is correct; the exact-path
  metric is not. Normalize by basename when evaluating translations.
- **Auto docs routing is heuristic:** the BM25 margin is configurable and was
  tuned on the 48-query panel. A code query with strong documentation words can
  still be routed to docs; `intent="code"` is the escape hatch.
- **Graph rebuild is separate from text reindex:** with
  `MSCODEBASE_DENSE_OFF=true`, a full vector reindex is intentionally blocked.
  Use `scripts/rebuild_graph.py` for the graph and
  `scripts/reindex_text_only.py` for chunks.
- **No 95% claim:** static retrieval and the tested local rerankers did not
  reach it on the internal panel. An LLM planner/agent loop is a different
  experiment and is not the default path.
- **Fast mode is not quality mode:** it is faster but materially less accurate
  on mixed natural-language questions. Use it for exact names and known paths.
- **Visible tools are allowlisted:** seeing "64 tools" in source does not mean
  all 64 are exposed to a given client; check `MSCODEBASE_MCP_TOOLS`.

## Reporting a bug

A useful report for this project is a small experiment, not just a number.
Please include:

1. The exact tool call and parameters (`query`, `mode`, `intent`, `limit`).
2. `debug_runtime_passport()` output and
   `codebase(action="index", path="status")`.
3. Whether the graph was rebuilt (`scripts/rebuild_graph.py`) and whether
   `MSCODEBASE_DENSE_OFF` / `MSCODEBASE_ONDEMAND_RERANK` were enabled.
4. The expected file and the actual returned file(s), plus whether the match is
   exact-path or same-basename (translations count as the same document).
5. A minimal query that reproduces it, and the relevant log tail from
   `%LOCALAPPDATA%/mscodebase/logs/`.

This lets us separate four different failures that look alike: bad ranking,
missing candidate, stale/empty index, and a gold-label mismatch.

## Project structure

```text
src/
  main.py                 MCP entry point
  mcp/
    server.py             server creation
    server_factory.py     DI and lifecycle
    server_tools.py       tool registration and inline tools
    tools/                search, index, graph, memory, write, lifecycle tools
  core/
    search/               engine, FTS5/BM25, scoring, query plan, graph adapter
    indexing/             parser, chunk store, index pipeline, file guard
    intelligence/         project memory, incidents, health, jobs
    graph.py              PropertyGraph
    di_container.py       service collection
  config/settings.py      environment-backed settings
  providers/              optional embedders and rerankers
experiments/              frozen panels, run artifacts, summaries
scripts/                  install/reindex/graph/smoke utilities
tests/                    pytest suite
docs/                     architecture, installation, operations, research
```

## Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Focused search tests
pytest tests/test_search_docs.py tests/test_query_plan.py \
  tests/test_experiment_output_guard.py tests/test_searcher.py -q

# Full suite (integration/benchmark tests are selected by markers)
pytest tests/ -m "not integration and not benchmark"

# Live smoke: real services, no mocks
python scripts/smoke_e2e.py --project .
```

The repository uses Conventional Commits, keeps experiment inputs under
`experiments/**/frozen/`, and records results in `EXPERIMENTS_LOG.md`,
`AGENT_DIARY.md` and `KNOWN_ISSUES.md`.

## Documentation map

| Document | What it covers |
|---|---|
| [docs/en/INSTALL.md](docs/en/INSTALL.md) | Installation, uninstall, platform notes |
| [docs/en/ARCHITECTURE.md](docs/en/ARCHITECTURE.md) | Layers, DI, module boundaries |
| [docs/en/ARCHITECTURE_DEEP.md](docs/en/ARCHITECTURE_DEEP.md) | Pipeline and lifecycle in depth |
| [docs/en/SEARCH_PIPELINE.md](docs/en/SEARCH_PIPELINE.md) | Retrieval, fusion, scoring, rerank |
| [docs/en/GRACEFUL_DEGRADATION.md](docs/en/GRACEFUL_DEGRADATION.md) | Behavior when providers are unavailable |
| [docs/en/ZED_WINDOWS_QUIRKS.md](docs/en/ZED_WINDOWS_QUIRKS.md) | Windows and Zed-specific behavior |
| [docs/en/CHANGELOG.md](docs/en/CHANGELOG.md) | Version history |
| [AGENTS.md](AGENTS.md) | Rules for AI agents working in this repository |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | Open debt and observations |
| [EXPERIMENTS_LOG.md](EXPERIMENTS_LOG.md) | Experiment hypotheses and raw results |

## Research notes

- [PageRank vs RAG on a real codebase](https://dev.to/mansio/i-measured-pagerank-token-savings-on-a-real-codebase-the-result-will-surprise-you-5bnj)
- [Fact-checking one AI's audit with another](https://dev.to/mansio/i-asked-one-ai-to-fact-check-another-ais-audit-of-my-own-code-1ac3)
- [The silent vector contamination bug](https://dev.to/mansio/the-silent-vector-contamination-bug-why-your-concurrent-embeddings-might-be-lying-to-you-5fg7)

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgments

Zed, the Model Context Protocol, Tree-sitter, SQLite/FTS5, and the local
inference projects that make an offline-first assistant practical.
