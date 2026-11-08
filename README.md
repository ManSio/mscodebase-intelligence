<div align="center">

<img src="logo/baner.png" alt="MSCodeBase Banner" width="100%"/>

[English](README.md) · [Русский](docs/ru/README.md) · [中文](docs/zh/README.md)

# MSCodebase Intelligence

**Local-first code intelligence for OpenCode and Zed: one question in, parallel retrieval out — lexical search, call graph, impact analysis, project memory and safe writes, over MCP.**

[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Zed](https://img.shields.io/badge/Zed-extension-orange.svg)](https://zed.dev/)

*Last rewritten: 2026-11-08. This page describes the code as it is today; the English page is authoritative.*

</div>

---

## What this is

MSCodebase Intelligence is a **local MCP server** that gives an AI assistant in
OpenCode (or Zed) a grounded view of a codebase. It is not a chat model and not a
replacement for the editor's language server. It answers four kinds of questions:

- Where is this symbol defined, who calls it, and what breaks if it changes?
- Which files matter for this question — code, tests, or documentation?
- What did this project already decide, and which incidents are still open?
- Can a rename/move/replace be previewed and applied safely?

The default runtime is **text-first**: SQLite FTS5/BM25 over parsed chunks plus
a Tree-sitter/PropertyGraph index. Embeddings and rerankers are optional; no
GPU, network or vector database is required to answer a code question.

## What works today

| Area | What it does | Entry point |
|---|---|---|
| **One-call investigation** | One question → search + symbols + grep in parallel, then impact + callers + tests + project memory; merged by file:line with provenance and `degraded[]` | `investigate` |
| Code search | BM25/FTS5 over parsed chunks; identifier short-circuit through the graph; optional on-demand rerank of the top candidates | `search_code` |
| Docs search | Separate `docs/**` FTS channel, selected when the BM25 margin is strong (no LLM router) | `search_code` |
| Regex search | Regex with AST-aware `scope=code` that skips comments and strings, judged per match | `grep_code` |
| Symbol intelligence | Definition, callers, callees, references, impact, structural search | `get_symbol_info`, `impact_analysis` |
| Graph | PropertyGraph of files/symbols with call, import, assignment, decorator and override edges | `graph_query`, `codebase` |
| Project memory | ADRs, incidents, known issues, retract/supersede lifecycle | `intel_*` (hidden by default) |
| Safe writes | Rename, move, delete, replace, insert with impact guards and receipts | `codebase(action=…)` |
| Diagnostics | Health, index status, logs, runtime counters, predicted change | `get_health_report`, `predict_change` |
| Tool discovery | Active profile, visible tools, hidden tools and how to enable them | `tool_help` |

## How a question is answered

`investigate` is the default entry point. It does not make the model choose
between tools; it runs the relevant channels itself and merges the answers.

```
investigate("how does the indexer decide to reindex a file")
        │
        ├─ pass 1 (parallel)   search ─ symbols ─ grep
        │                      each with its own timeout
        ▼
        ├─ pass 2 (parallel)   impact ─ callers ─ tests ─ project memory
        │                      only for what pass 1 found
        ▼
   merge by (file, line): one row per hit, channels unioned  [search+graph]
   provenance on every item, degraded[] for a slow/failed channel
```

Rules that matter:

- A slow channel **degrades** the answer (`degraded: grep:timeout`); it never
  fails the call.
- A question with no matches returns an explicit "nothing found" — never a
  plausible guess.
- The merged answer is capped (default 8 rows, 180 characters of text each), so
  it does not flood the context.
- `search_code`, `grep_code`, `get_symbol_info` and `impact_analysis` stay
  available for a precise follow-up.

## Search quality: measured, with its limits

Numbers only mean something with the measuring stick attached. These come from
an internal **48-query panel** (33 real project questions plus 15
docstring-derived ones), on a clean index with `experiments/**` excluded.
Snapshot date: **2026-10-25**; re-run the harnesses under `experiments/`
before quoting them as current.

| Path | hit@1 | hit@5 |
|---|---:|---:|
| Code, quality mode | 0.825 | 0.900 |
| Overall, quality mode | 0.688 | 0.750 |
| Overall, auto docs route | 0.792 | 0.875 |
| Fast mode | 0.542 | 0.729 |
| Docs, exact path | 0.000 | 0.125 |
| Docs, same basename | 0.750 | 0.750 |

What this does **not** mean:

- It is **not** 95% accuracy. Static retrieval on this panel did not reach it;
  a two-channel repo map topped out around 40% / 62% / 73% at 1k / 2k / 4k
  tokens with perfect routing.
- It does **not** mean every reranker helps. Several local rerankers were
  measured and rejected: they lowered hit@1 or added unacceptable latency.
- It does **not** mean the docs path is broken: it often returns the right
  document in another language (`docs/ru/X` for `docs/en/X`). That is a
  gold-labeling property, not a retrieval failure.

The panel, hypotheses and raw runs live under `experiments/`. Every public
number and the command that regenerates it are listed in
**[docs/FACTS.md](docs/FACTS.md)**.

## Quick start

Requirements: Windows is the validated platform; Python 3.14+; an MCP host
(**OpenCode is the primary one**, the Zed extension still works).

```bash
cd <repo-root>
python install.py            # full install: venv, pip, optional models
python install.py --sync     # code-only sync into the installed copy
```

Restart the host after `install.py` finishes (the OpenCode session, or the Zed
window). The installed copy lives in `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`
and both hosts launch that venv. Verify from the agent panel:

```text
tool_help()                        # profile, visible and hidden tools
get_health_report()                # index, embedder, resources
codebase(action="index", path="status")
```

If the text index is missing or stale, rebuild chunks and graph without
embeddings (measured: 498 files, 7 375 chunks, 262–266 s on this repository):

```bash
python scripts/reindex_text_only.py --project .
```

If only the graph is empty while chunks exist:

```bash
python scripts/rebuild_graph.py
```

Then restart the MCP server so the new process opens the rebuilt stores.

## Tools and the profile

The server registers **69 tools** (36 core + 16 intel + 13 inline + 4 dev);
`execute_script` is an optional 70th behind
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`. That is too many for a model to pick
from, so the client sees a **profile**:

| Profile | Visible | What it contains |
|---|---:|---|
| `core` (default) | **17** | one entry per intent + 4 maintenance tools |
| `full` | **69** | everything registered |

`MSCODEBASE_MCP_TOOLS` remains an explicit comma-separated allowlist and
overrides the profile when set. `tool_help()` reports the active profile, the
visible tools with a one-line intent, and the hidden names.

Default-visible 17:

| Tool | Purpose |
|---|---|
| `investigate` | one query → parallel channels, merged with provenance |
| `search_code` | ranked code/docs search (FTS5/BM25, docs routing) |
| `grep_code` | regex search; `scope=code` skips comments/strings |
| `get_symbol_info` | definition, callers, callees |
| `impact_analysis` | what breaks if a symbol changes |
| `graph_query` | related files, variable flow, cypher, impact |
| `codebase` | hub: index status, git, write actions |
| `read_live_file` | read a line range from disk |
| `notify_change` | tell the index a file changed |
| `get_health_report` | index, embedder, resources, search quality |
| `intel_get_project_memory` | ADRs, incidents, known issues |
| `predict_change` | changed files, affected tests, risk |
| `tool_help` | profile and discovery |
| `generate_docs`, `bump_version`, `auto_update_docs`, `install_git_hooks` | maintenance |

Hidden by default (registered, not exposed): the six `lsp_*` tools,
`plan_search`, `structural_search`, the 16 `intel_*` mutation/lifecycle tools,
`submit_background_task` / `get_task_status` / `verify_action` /
`get_action_receipt`, `ack_impact`, and the frame/rank/scan helpers. Set
`MSCODEBASE_MCP_PROFILE=full` to expose them; nothing is removed from the
server, only filtered from the client surface.

## Architecture

```text
MCP host: OpenCode (primary) or Zed
 │
 ├── host built-in LSP (autocomplete, diagnostics)
 │
 └── MCP client
      │
      ▼
 MSCodebase MCP server
  ├── investigate   two-pass parallel fan-out, merged with provenance
  ├── Search        SQLite FTS5/BM25, symbol/path signals, docs routing
  ├── Graph         PropertyGraph: calls, imports, assignments, decorators, overrides
  ├── Index         parser → chunks → FTS5 + graph; incremental freshness checks
  ├── Memory        ADRs, incidents, known issues, retract/supersede
  ├── Writes        rename/move/delete/replace/insert with impact guards
  ├── Diagnostics   health, jobs, logs, telemetry, change preview
  └── Optional      embedding providers, reranker, LSP rename
```

Canonical data locations (outside the repository):

- `%LOCALAPPDATA%/mscodebase/projects/<hash>/` — per-project graph, memory,
  job state, commit memory, telemetry.
- `%LOCALAPPDATA%/mscodebase/logs/` — server logs.
- `<project>/.mscodebase/chunks.db` — the text chunk store used by the default
  search path.

LanceDB is part of the optional vector path and is not required by the default
text-first configuration.

## Configuration

Settings are environment variables with defaults in `src/config/settings.py`.
The ones that change behaviour most:

| Variable | Default | Effect |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | Skip dense/vector retrieval; use FTS5, symbols, graph |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | Use the SQLite/FTS5 chunk store |
| `MSCODEBASE_ONDEMAND_RERANK` | `true` | Rerank the top candidates with live embeddings |
| `MSCODEBASE_DOCS_MARGIN` | `4.0` | Docs routing threshold (docs score − code score) |
| `MSCODEBASE_AUGMENT_CHUNKS` | `true` | Prepend FILE/SYMBOLS/DOC to chunk text |
| `MSCODEBASE_TESTS_SIGNAL` | `false` | Append covering tests to symbol results |
| `MSCODEBASE_CODE_BM25` | `false` | Identifier-aware BM25 scoring |
| `MSCODEBASE_RU_SYNONYMS` | `false` | Russian → English code-term expansion |
| `MSCODEBASE_MCP_PROFILE` | `core` | Tool surface: 17 visible, or all 69 with `full` |
| `MSCODEBASE_MCP_TOOLS` | — | Explicit allowlist; overrides the profile |

`experiments/**` is intentionally excluded from indexing: it contains frozen
panels and run artifacts, and indexing them previously made BM25 return the
panel instead of the code. The files stay tracked in git.

## Supported languages

Python is the primary, fully exercised language. Tree-sitter parsing covers
JavaScript, TypeScript/TSX, Rust, Go, Java, C#, Ruby, PHP, Kotlin, Swift, C,
C++, Scala and Dart; SQL, YAML, TOML, HTML, CSS and HCL/Terraform are indexed
as context, without the same call-graph coverage. The current build loads
**31 grammars**. Graph and data-flow depth depend on the grammar.

<!-- stale-ignore -->
Versions are pinned for reproducibility: `tree-sitter==0.26.0` (the latest
Python binding on PyPI), `tree-sitter-language-pack==1.25.0`, and one pinned
release per grammar package. A grammar bump changes chunking, so it requires a
reindex and a symbol-count comparison, not a routine upgrade.
<!-- stale-ignore -->

## Limitations

Deliberate, documented boundaries rather than hidden behaviour:

- **Docs gold vs language:** the docs channel may return `docs/ru/X.md` when
  the gold is `docs/en/X.md`. Normalize by basename when evaluating.
- **Auto docs routing is heuristic:** a code query with strong documentation
  words can still be routed to docs; `intent="code"` is the escape hatch.
- **Full vector reindex is blocked** while `MSCODEBASE_DENSE_OFF=true`. Use
  `scripts/rebuild_graph.py` for the graph and
  `scripts/reindex_text_only.py` for chunks.
- **No 95% claim.** Static retrieval and the tested local rerankers did not
  reach it. An LLM planner is a separate experiment, not the default path.
- **Fast mode is not quality mode:** faster, materially less accurate on mixed
  natural-language questions.
- **Tool visibility is a profile:** 69 registered, 17 visible. If a tool you
  expect is missing, run `tool_help()` and switch the profile.
- **LSP tools need a working basedpyright:** they fail fast with a clear
  message when it is missing, and the result is cached for 30 seconds.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Focused search tests
pytest tests/test_search_docs.py tests/test_query_plan.py tests/test_searcher.py -q

# Full suite (integration/benchmark selected by markers)
pytest tests/ -m "not integration and not benchmark"

# Live smoke: real services, no mocks
python scripts/smoke_e2e.py --project .
```

The repository uses Conventional Commits, keeps experiment inputs under
`experiments/**/frozen/`, and records results in `EXPERIMENTS_LOG.md`,
`AGENT_DIARY.md` and `KNOWN_ISSUES.md`.

## Reporting a bug

A useful report is a small experiment:

1. The exact tool call and parameters (`query`, `mode`, `intent`, `limit`).
2. `tool_help()` / `get_health_report()` and
   `codebase(action="index", path="status")`.
3. Whether the graph was rebuilt and which flags were set
   (`MSCODEBASE_DENSE_OFF`, `MSCODEBASE_ONDEMAND_RERANK`, profile).
4. The expected file and the actual file(s), and whether the match is
   exact-path or same-basename.
5. The relevant log tail from `%LOCALAPPDATA%/mscodebase/logs/`.

That separates four failures that look alike: bad ranking, missing candidate,
stale/empty index, and gold-label mismatch.

## Documentation map

| Document | What it covers |
|---|---|
| [docs/FACTS.md](docs/FACTS.md) | Every public number and the command that regenerates it |
| [docs/en/ARCHITECTURE.md](docs/en/ARCHITECTURE.md) | Layers, DI, module boundaries, tool profile |
| [docs/en/SEARCH_PIPELINE.md](docs/en/SEARCH_PIPELINE.md) | Retrieval, ranking, docs routing, investigate fan-out |
| [docs/en/INSTALL.md](docs/en/INSTALL.md) | Installation, the sync/restart loop, troubleshooting |
| [docs/en/CONFIGURATION.md](docs/en/CONFIGURATION.md) | Every environment variable and its default |
| [docs/en/CLIENTS.md](docs/en/CLIENTS.md) | OpenCode, Zed, Claude Code, VS Code, CLI, Docker |
| [docs/en/HOOKS_AND_GATES.md](docs/en/HOOKS_AND_GATES.md) | The OpenCode plugin, the 12 pre-commit gates, CI jobs |
| [docs/en/FAQ.md](docs/en/FAQ.md) | Short answers to the questions that come up first |
| [docs/en/SECURITY.md](docs/en/SECURITY.md) | Threat model of a local MCP server |
| [docs/en/GRACEFUL_DEGRADATION.md](docs/en/GRACEFUL_DEGRADATION.md) | Behaviour when providers are unavailable |
| [docs/en/ZED_WINDOWS_QUIRKS.md](docs/en/ZED_WINDOWS_QUIRKS.md) | Windows behaviour shared by both hosts |
| [docs/en/CHANGELOG.md](docs/en/CHANGELOG.md) | Version history |
| [AGENTS.md](AGENTS.md) | Rules for AI agents working in this repository |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | Open debt and observations |
| [EXPERIMENTS_LOG.md](EXPERIMENTS_LOG.md) | Experiment hypotheses and raw results |

Russian and Chinese translations of every canonical page live in
`docs/ru/` and `docs/zh/` with the same file names.

Historical material (blog posts, research notes, archived diaries) is kept for
provenance and carries a status banner; it is not a description of today.

## License

MIT. See [LICENSE](LICENSE).
