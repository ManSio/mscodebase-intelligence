<div align="center">

<img src="logo/baner.png" alt="MSCodeBase Banner" width="100%"/>

[🇬🇧 English](README.md) • [🇷🇺 Русский](docs/ru/README.md) • [🇨🇳 中文](docs/zh/README.md)

# MSCodebase Intelligence

**AI-powered semantic code search for Zed IDE — deep code analysis MCP server**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Zed](https://img.shields.io/badge/Zed-extension-orange.svg)](https://zed.dev/)
[![CI](https://github.com/ManSio/mscodebase-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/ManSio/mscodebase-intelligence/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-553%762 passed-brightgreen)](tests/)

[Features](#-features) • [Quick Start](#-quick-start) • [Tools](#-mcp-tools-0-total) • [Documentation](#-documentation-map) • [Installation](docs/en/INSTALL.md) • [Architecture](docs/en/ARCHITECTURE.md) • [Contributing](CONTRIBUTING.md) • [Security](SECURITY.md)

*Last updated: 2026-07-21*

</div>

---

## 🎯 Positioning

**MSCodeBase Intelligence** is an MCP server for **Zed IDE** that gives AI assistants **deep understanding of the entire codebase**: semantic search, call graph, project memory, diagnostics.

This is **not** an LSP server or a replacement for the editor's built-in autocomplete. It's a "code intelligence" layer on top of the editor:

```
┌─────────────────────────────────────────────────────┐
│                      Zed IDE                         │
│  ┌───────────────────────────────────────────────┐  │
│  │        LSP (built-in autocomplete,           │  │
│  │        inline hints, diagnostics)            │  │
│  └───────────────────────────────────────────────┘  │
│                        │                              │
│                        ▼                              │
│  ┌───────────────────────────────────────────────┐  │
│  │  MSCodeBase (MCP server)                     │  │
│  │  · Semantic search across the codebase       │  │
│  │  · Call graph & impact analysis              │  │
│  │  · Project memory (ADR, tech debt)           │  │
│  │  · Self-diagnostics and self-healing         │  │
│  │  · 42 tools for AI assistant                 │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### What you get

| Feature | MSCodeBase | Standard LSP (pyright/pylsp) |
|---------|:----------:|:---------------------------:|
| 🔍 **Semantic search** (BM25 + Vector + Reranker) | ✅ | ❌ |
| 🧠 **Call graph + impact analysis** | ✅ | ❌ |
| 🗃️ **Project memory** (ADR, known issues) | ✅ | ❌ |
| 🏥 **Self-diagnosis + self-healing** | ✅ | ❌ |
| 🔎 **Cross-repo search** | ✅ | ❌ |
| 🤖 **RAG answer generation** (mode=ask) | ✅ | ❌ |
| 🔬 **Search explainability** (per-stage score trace) | ✅ | ❌ |
| 🏛️ **Architecture drift detection** (chain/circular/hub) | ✅ | ❌ |
| ✅ **Claim verification** (agent fact-checking vs code) | ✅ | ❌ |
| ✏️ **Inline autocomplete** | ❌ | ✅ |
| 🏷️ **Inlay hints** | ❌ | ✅ |

### LSP: Hybrid Rename Only

MSCodeBase **uses LSP only for `rename_symbol`** — the LSP client (`src/core/lsp_client.py`) spawns **pyright-langserver** for precise cross-file rename, with graceful fallback to SymbolIndex (Tree-sitter) on timeout. All other functionality is implemented through **38 MCP tools**.

The standalone LSP server (`src/lsp_main.py`) was experimental and **does not work in Zed** — see [LSP_WONTFIX.md](docs/en/investigations/LSP_WONTFIX.md).

### Platforms

Designed and tested on **Windows**. macOS and Linux should work but have not been validated officially.

### Languages

| Language | Parsing | Call Graph | Data Flow (ASSIGNED_FROM) |
|---|---|---|---|
| **Python** | ✅ | ✅ | ✅ |
| **TypeScript** | ✅ | ✅ | ✅ |
| **TSX** | ✅ | ✅ | ✅ |
| **Rust** | ✅ | ✅ | ✅ |
| **Go** | ✅ | ✅ | ✅ |
| **JavaScript** | ✅ | ✅ | ✅ |
| **Java** | ✅ | ✅ | ✅ |
| **C#** | ✅ | ✅ | ✅ |
| **Ruby** | ✅ | ✅ | ✅ |
| **PHP** | ✅ | ✅ | ✅ |
| **Kotlin** | ✅ | ✅ | ✅ |
| **Swift** | ✅ | ✅ | ✅ |
| **C** | ✅ | ✅ | ✅ |
| **C++** | ✅ | ✅ | ✅ |
| **Scala** | ✅ | ✅ | ✅ |
| **Dart** | ✅ | ✅ | ✅ |
| **Shell / Bash** | ✅ | ✅ | ❌ (грамматика без RHS-field) |
| **SQL** | ✅ (context) | ❌ | ❌ |
| **YAML** | ✅ (context) | ❌ | ❌ |
| **TOML** | ✅ (context) | ❌ | ❌ |
| **HTML** | ✅ (context) | ❌ | ❌ |
| **CSS** | ✅ (context) | ❌ | ❌ |
| **HCL / Terraform** | ✅ (context) | ❌ | ❌ |

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔍 **Unified Search** | `search_code(query, mode, intent_hint)` — single tool: fast/quality/deep/context/ask/auto |
| 🧠 **Intelligence Layer** | 0 high-level `intel_*` tools: self-diagnostics, topology, memory, error prediction |
| 🌐 **Cross-repo Search** | Search across multiple projects with `@mention` syntax |
| 🌳 **Call Graph** | Full call graph: definition + callers + callees + impact analysis |
| 🏗 **Structural Search** | 13 AST patterns (class_inheritance, async_function, decorator, etc.) |
| 🔎 **Context Search** | Find similar code — paste a fragment, get semantic duplicates |
| 🪣 **Multi-Bucket RAG** | Code/docs buckets, soft weighting, intent_hint (code/docs/auto) |
| 🤖 **mode=ask** | RAG answer generation via phi-4 (server profile) |
| 💾 **LanceDB v2** | Vector DB with per-project isolation (incremental BM25 reindex) |
| 🛡 **Rate Limiting** | DebounceBatch + CircuitBreaker — protection against VFS loops |
| 🏥 **Self-Diagnosis** | `get_health_report` + `index_health` — full check and recovery |
| 🧪 **Clean Architecture** | DI Container (18 services), 43 tools (18 core + 13 intel + 12 inline), 553+ tests |
| 🪟 **Multi-Window** | `ProjectIndexerRegistry` — isolated Indexer per project, LRU 5, ResourceMonitor throttle |
| ✏️ **Write Tools** | `codebase(action=...)` — unified hub: rename, move, delete, replace, insert, ack |
| ⚡ **Meta-Patching** | LanceDB `move_chunks_metadata` — file_path rename without re-embedding (50ms vs 5s) |
| 🔗 **Data Flow Graph** | `ASSIGNED_FROM` edges track variable assignments. Unified Walker + Conditional Flow (if/for/while/try). 42 edge types in PropertyGraph. |
| ⚙️ **SYSTEM_PROFILE** | `light` (sync) / `server` (async with phi-4) |
| 🎯 **MMR Diversification** | Maximal Marginal Relevance (λ=0.6) после RRF — убирает дубли, сохраняя релевантность. 0.3ms на 50 docs. |
| 🧠 **Auto Intent Detection** | Keyword-based автоопределение code/docs по тексту запроса. Не требует ручного `intent_hint`. |
| 📖 **Extended Synonyms** | 39 групп синонимов (auth↔login, function↔method, cache↔buffer и др.) — закрывает разрыв между терминологией пользователя и кодом. |

---

## 🚀 Quick Start

Install the `mscodebase-intelligence` extension in Zed, then:

```bash
cd D:\Project\MSCodeBase
python install.py

# Quick sync (code only, no prompts):
python install.py --sync

# CI mode (no prompts, fail fast):
python install.py --yes

# Skip model downloads:
python install.py --skip-models

# Restart Zed (File → Quit → reopen)
# Verify: intel_get_runtime_status()
```

**install.py does:**
1. Copies 39+ source files to the extension directory
2. Installs Python dependencies
3. Downloads llama-server.exe + GGUF reranker model (bge-reranker-v2-m3). The embedder (multilingual-e5-small INT8) is an ONNX model downloaded separately.
4. Configures MCP in Zed's settings.json

See also: [AI_INSTALLATION_PROMPT.md](AI_INSTALLATION_PROMPT.md), [docs/en/INSTALL.md](docs/en/INSTALL.md)

### Providers

MCP auto-selects the best available provider:

```
ONNX INT8 (in-process)         → llama.cpp GGUF (GPU) → LM Studio (if running) → BM25 only
   ~0.5 GB RAM                    ~1.7 GB RAM (2× llama-server)   ~6 GB RAM          no embeddings
   e5-small embedder (384dim)     reranker (bge-reranker-v2-m3)     external API
```

> Embedding runs **in-process** via ONNX Runtime e5-small INT8 (~52 ch/s on Windows CPU).
> The reranker runs as a separate `llama-server.exe` process serving the BGE-M3 GGUF model.
> LM Studio is only an optional fallback provider if the local ONNX model is unavailable.

Benchmarks: [docs/research/2026-07-10-final-benchmark.md](docs/research/2026-07-10-final-benchmark.md)

---

## 📚 Documentation Map

| Document | Description | Audience | Languages |
|----------|-------------|----------|-----------|
| **[docs/en/INSTALL.md](docs/en/INSTALL.md)** | Installation, setup, uninstall | Users | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/ARCHITECTURE.md](docs/en/ARCHITECTURE.md)** | Clean Architecture, Layers, DI | Developers | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/ARCHITECTURE_DEEP.md](docs/en/ARCHITECTURE_DEEP.md)** | Deep architecture: pipeline, lifecycle, comparison | Architects | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/SEARCH_PIPELINE.md](docs/en/SEARCH_PIPELINE.md)** | Search pipeline: BM25 → RRF → Reranker | Developers | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/GRACEFUL_DEGRADATION.md](docs/en/GRACEFUL_DEGRADATION.md)** | 5 levels of graceful degradation (llama.cpp → ONNX → BM25) | DevOps | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/ARCHITECTURE_LAYERS.md](docs/en/ARCHITECTURE_LAYERS.md)** | 10 runtime layers | Architects | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/FAQ.md](docs/en/FAQ.md)** | Frequently Asked Questions | All | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/TELEMETRY.md](docs/en/TELEMETRY.md)** | Metrics, ETA, data collection | DevOps | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/investigations/ONNX_SESSION_REPORT.md](docs/en/investigations/ONNX_SESSION_REPORT.md)** | Full ONNX migration, 7 fixes, benchmarks | Support | 🇬🇧 |
| **[docs/en/investigations/LSP_WONTFIX.md](docs/en/investigations/LSP_WONTFIX.md)** | LSP on Windows investigation (WONTFIX) | Support | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/ZED_WINDOWS_QUIRKS.md](docs/en/ZED_WINDOWS_QUIRKS.md)** | Windows specifics, Restricted Mode | Windows users | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/CHANGELOG.md](docs/en/CHANGELOG.md)** | Version history | All | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/CONTRIBUTING.md](docs/en/CONTRIBUTING.md)** | How to contribute, PRs | Contributors | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/SECURITY.md](docs/en/SECURITY.md)** | Security policy, vulnerabilities | Security | 🇬🇧 🇷🇺 🇨🇳 |
| **[AGENTS.md](AGENTS.md)** | AI Agent system rules | AI Agent | 🇬🇧 |
| **[SECURITY.md](SECURITY.md)** | Security policy, reporting vulnerabilities | Security | 🇬🇧 |
| **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** | Community standards | Contributors | 🇬🇧 |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | How to contribute (root-level) | Contributors | 🇬🇧 |
| **[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)** | Known issues & technical debt registry | All | 🇬🇧 |

All documents are cross-referenced. Available in 3 languages: English, Русский, 中文.

---

## 🔧 MCP Tools (42 total)

### Core Search

| Tool | When to Use |
|------|-------------|
| `search_code(query, mode, filter_layer, intent_hint)` | **Main search tool.** `mode="auto"` / `"fast"` / `"quality"` / `"deep"` / `"context"` / `"ask"`. `intent_hint="code"` / `"docs"` / `"auto"` — soft bucket weighting. `filter_layer="core"` — search within specific architecture layer |
| `structural_search(pattern)` | AST search: `class_inheritance`, `async_function`, `function_with_decorator` and more |
| `cross_repo_search(query @repo)` | Search across multiple projects (mono-repo) |
| `cross_project_deps(action)` | Cross-project dependency graph: `graph` / `deps` / `cycles` / `impact` |
| `get_symbol_info(query)` | Call Graph: callers, callees, impact files |
| `execute_script(code, timeout, args)` | **Sandboxed Python execution.** TempDirectory isolation, PYTHONPATH=project, graceful shutdown. Returns structured `{stdout, stderr, exit_code, duration_ms, truncated, timed_out}` |
| `impact_analysis(symbol)` | Symbol change impact analysis (risk score, depth) |

### Index Management

| Tool | When to Use |
|------|-------------|
| `get_index_status()` | Index status: chunks, files, symbols |
| `get_index_progress()` | Indexing progress (phase, percent) |
| `index_project_dir(path)` | Start full project indexing |
| `get_index_timeline()` | Indexing history by date |
| `index_health(project_root)` | Index diagnostics and self-recovery |
| `notify_change(file_path)` | Force index update for a file (via DebounceBatch) |
| `generate_chunk_summaries(root)` | LLM-generated descriptions for code chunks |
| `scan_changes(project_root)` | Architectural diff — analyze changes since last baseline |

### System & Diagnostics

| Tool | When to Use |
|------|-------------|
| `get_health_report()` | **Full self-diagnosis:** index, embedder, logs, synchronization |
| `get_logs(project_root)` | Latest errors and warnings from project logs |
| `read_live_file(path)` | Read file from LSP memory (including unsaved changes) |

### Analytics

| Tool | When to Use |
|------|-------------|
| `get_hotspots(project_root)` | Hotspots — files with high bug rate |
| `get_repo_rank(project_root, top_k)` | Symbol importance ranking (PageRank on call graph) |
| `get_bug_correlation(project_root)` | Bug-change correlation analysis |
| `get_repo_map(project_root)` | Project map: file tree + key symbols |
| `get_related_files(project_root, path)` | Files related via co-change / bug correlation |
| `graph_query(action, target)` | Graph queries: `impact` / `feature` / `deps` / `tests` / `cypher` / `flow` / `drift` / `verify` |
| `find_similar_bugs(error)` | Find similar bugs from history by error text |

### Git & History

| Tool | When to Use |
|------|-------------|
| `get_commit_history(root, limit)` | Semantic commit history |
| `get_file_history(root, path)` | Change history for a specific file |
| `get_branch_info(project_root)` | Branch info + index status |

### Lifecycle & Verification

| Tool | When to Use |
|------|-------------|
| `submit_background_task(type, root)` | Run long tasks: `bug_correlation` / `build_knowledge_graph` / `full_analysis` |
| `get_task_status(task_id)` | Background task status |
| `verify_action(action_type)` | Verification: `file_write` / `git_commit` / `git_push` / `index_sync` |

### Write Tools — `codebase(action=...)`

| Action | When to Use |
|--------|-------------|
| `codebase(action="rename", old, new, apply)` | Rename symbol across all files (preview/apply, collision check) |
| `codebase(action="move", symbol, to_file, apply)` | Move symbol to another file (preview/apply, import updates) |
| `codebase(action="safe_delete", symbol, force, apply)` | Safe delete with reference check (force mode) |
| `codebase(action="replace", symbol, new_code, apply)` | Replace function/class body (preview/apply) |
| `codebase(action="insert_before", anchor, new_code, apply)` | Insert code before anchor symbol (preview/apply) |
| `codebase(action="insert_after", anchor, new_code, apply)` | Insert code after anchor's body (preview/apply) |
| `codebase(action="ack_impact", file_path)` | Acknowledge impact for modification guard |

### Intelligence Layer (intel_*) — 13 High-Level Tools

| Tool | What it does |
|------|-------------|
| `intel_get_runtime_status()` | Aggregated health status: embedder, index, resource usage |
| `intel_trigger_reindex()` | Fire-and-forget reindexing (does not block Zed) |
| `intel_get_job_status(job_id)` | Background task progress |
| `intel_code_topology(symbol)` | Call graph + module topology (< 2 sec) |
| `intel_get_project_memory()` | Project memory map: ADR, known_issues, tech_debt |
| `intel_log_incident(...)` | Log an incident to project history |
| `intel_analyze_incident(error)` | Find similar incidents + ready-made solutions |
| `intel_add_memory_node(section, data)` | Add a record to project memory |
| `intel_get_hotspots()` | Top-5 files with highest bug load |
| `intel_predict_root_cause(error)` | Predict root cause from logs + history |
| `intel_get_telemetry(days)` | Per-tool telemetry, resource usage, LLM stats |
| `intel_auto_collect_adrs(max_commits)` | Auto-generate ADRs from commit history |
| `intel_reset_index()` | Delete and rebuild index from scratch |

> `intel_tool_health()`, `intel_explain_project_state()`, `intel_get_project_context()` — see Diagnostic Tools below.

### Dev Tools (4)

| Tool | What it does |
|------|-------------|
| `generate_docs(project_root)` | Generate Markdown docs from PropertyGraph (DEPRECATED — use auto_update_docs) |
| `bump_version(project_root, part, dry_run)` | Bump project version + update CHANGELOG |
| `auto_update_docs(project_root, action)` | Auto-update documentation: update/check |
| `install_git_hooks(project_root, action)` | Install pre-commit hooks: install/uninstall/status |

### Diagnostic Tools (7)

| Tool | What it does |
|------|-------------|
| `debug_runtime_passport()` | Process passport: RUN_ID, PID, build info |
| `get_runtime_counters()` | Runtime counters: calls, blocks, warnings |
| `intel_execution_timeline(limit)` | Recent action timeline with durations |
| `intel_get_project_context(root)` | Single snapshot: state, index, health, memory |
| `intel_explain_project_state(root)` | Human-readable project state diagnosis |
| `intel_tool_health()` | Tool success rates, latency, confidence |
| `refresh_db_connection()` | Reset database handle and reconnect |

---

## 🏗️ Architecture

### Clean Architecture with DI Container

```
┌──────────────────────────────────────────────────────────────────┐
│                   MCP Server (~600 lines)                         │
│            src/mcp/server.py + server_tools.py + server_factory.py │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
|  │              DI Container (18 services)                   │   │
│  │  src/core/di_container.py — ServiceCollection              │   │
│  │                                                           │   │
│  │  ┌──────────┐  ┌────────────┐  ┌──────────────────────┐  │   │
│  │  │ Indexer  │  │  Searcher  │  │  DebounceBatch       │  │   │
│  │  │ Embedder │  │  SymbolIdx │  │  CircuitBreaker      │  │   │
│  │  │ Parser   │  │  FileGuard │  │  RateLimiter         │  │   │
│  │  └──────────┘  └────────────┘  └──────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                       │
│              ┌────────────┴────────────┐                         │
│              ▼                          ▼                         │
│  ┌────────────────────┐  ┌────────────────────────────────────┐  │
│  │  18 Tool Classes   │  │  13 intel_* + 7 inline tools    │  │
│  │  src/mcp/tools/*.py │  │  intelligence/layer.py +           │  │
│  │  + codebase hub     │  │  server_tools.py (inline)          │  │
│  │  Constructor Inj.   │  │  error_boundary decorator          │
│  │  1 execute_script   │  │  asyncio.wait_for(timeout)        │  │
│  └────────────────────┘  └────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐     ┌───────────────────┐
│  RemoteEmbedder  │     │  LanceDB v2       │
│  (ONNX Runtime     │     │  (Vector DB)       │
│   e5-small INT8,    │     │  BM25 + Vector    │
│   in-process;      │     │                    │
│   LM Studio/Ollama │     │                    │
│   fallback)        │     │                    │
└─────────────────┘     └───────────────────┘
```

---

## ⚡ Performance

| Mode | Latency | Best For |
|:-----|:--------|:---------|
| `search_code(query, mode="fast")` | ~80-500ms | Simple keyword / exact name |
| `search_code(query, mode="quality")` | ~250-2000ms | Semantic search with reranker |
| `search_code(query, mode="deep")` | ~2-5s | Complex research across modules |
| `search_code(query, mode="context")` | ~200-800ms | Find similar code by fragment |
| `get_symbol_info(query)` | ~200-1500ms | Symbol definition + call graph |
| `impact_analysis(symbol)` | ~1-5s | Change impact analysis |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LM_STUDIO_HOST` | `localhost` | LM Studio hostname |
| `LM_STUDIO_PORT` | `1234` | LM Studio port |
| `OLLAMA_HOST` | `localhost` | Ollama hostname |
| `OLLAMA_PORT` | `11434` | Ollama port |
| `EMBEDDING_MODEL` | `qwen3-embedding` | Default embedding model name |
| `LOG_LEVEL` | `INFO` | Logging verbosity level |
| `MSCODEBASE_MCP_TOOLS` | *(default set)* | Comma-separated list of visible tools (e.g. `search_code,codebase`) |
| `MSCODEBASE_EXECUTE_SCRIPT_ENABLED` | `false` | Enable `execute_script` tool (RCE risk) |
| `LLAMA_BACKEND` | `auto` | Reranker backend: `auto` / `msvc` (CPU) / `vulkan` (GPU) |

---

## 🔧 Troubleshooting

### MCP Server Not Responding

**Symptoms:** tools timeout, no response.

**Checklist:**
1. **File → Quit** → reopen the project
2. Run `python install.py` to reconfigure
3. Check logs: `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`

### Index Empty (0 chunks)

Run in Agent Panel:
```
intel_trigger_reindex()
```

Then verify: `get_index_status()`

### LM Studio Connection Issues

```bash
# Verify the server responds:
python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:1234/v1/health').read())"
```

Expected: `{"status":"ok"}`.

---

## 📁 Project Structure

```
mscodebase-intelligence/
├── src/
│   ├── main.py                     # MCP server entry point (~194 lines)
│   ├── mcp/
│   │   ├── server.py               # MCP server creation (~597 lines)
│   │   ├── server_factory.py       # DI setup + server lifecycle (~478 lines)
│   │   ├── server_tools.py         # Tool registration + 7 inline tools (~607 lines)
│   │   └── tools/                  # 11 modules + base class
│   │       ├── codebase_tool.py    # codebase(action=...) hub + execute_script
│   │       ├── search_tools.py     # search_code, get_symbol_info, impact_analysis
│   │       ├── indexing_tools.py   # notify_change, index_project_dir, index_health
│   │       ├── git_tools.py        # get_branch_info, get_commit_history, get_file_history
│   │       ├── system_tools.py     # get_index_status, get_health_report, read_live_file, get_logs
│   │       ├── analysis_tools.py   # structural_search, get_repo_map, get_repo_rank, scan_changes
│   │       ├── graph_tools.py      # cross_repo_search, cross_project_deps, graph_query
│   │       ├── investigation_tools.py  # get_bug_correlation, get_hotspots, find_similar_bugs
│   │       ├── lifecycle_tools.py  # submit_background_task, get_task_status, verify_action
│   │       ├── meta_tools.py       # IndexTool, GitTool, SystemTool (spoke tools for codebase hub)
│   │       └── write_tools.py      # WriteTool (rename, move, delete, replace, insert)
│   ├── core/                       # Business logic + backward-compat shims
│   │   ├── di_container.py         # ★ DI Container (18 services, ServiceCollection)
│   │   ├── error_handler.py        # error_boundary decorator + ToolError
│   │   ├── rate_limiter.py         # SlidingWindowRateLimiter + DebounceBatch + CircuitBreaker
│   │   ├── graph.py                # PropertyGraph (42 edge types)
│   │   ├── structural_search.py    # 13 AST patterns (Tree-sitter)
│   │   ├── lsp_client.py           # Thin LSP client (pyright JSON-RPC 2.0)
│   │   ├── intelligence_layer.py   # Shim → core/intelligence/layer.py
│   │   ├── indexing/               # 18 files: indexer, parser, symbol_index, file_guard, ...
│   │   ├── search/                 # 18 files: engine (Searcher), scoring, bm25, cypher_*, ...
│   │   └── intelligence/           # 5 files: layer (intel_* tools), jobs, health, context, store
│   ├── providers/
│   │   ├── embedder/
│   │   │   └── remote_embedder.py  # ONNX e5-small INT8 + LM Studio/Ollama fallback
│   │   └── reranker/               # llama_runner, multi_provider, search_result_reranker, scoring
│   ├── config/
│   │   └── settings.py             # All configuration via os.getenv (Single Source of Truth)
│   └── utils/                      # paths, i18n, ui_formatter, zed_config
├── docs/
│   ├── en/                         # English docs
│   ├── ru/                         # Russian docs
│   └── zh/                         # Chinese docs
├── scripts/                        # CLI utilities (install, sync, benchmark, audit)
├── tests/                          # 605 tests (pytest)
├── install.py                      # Installer (3 languages: en/ru/zh)
└── README.md
```

---

## 🛠️ Development

See [docs/en/CONTRIBUTING.md](docs/en/CONTRIBUTING.md) for:
- How to add new MCP tools
- Test structure and CI pipeline
- Commit message conventions

### Quick Start for Devs

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Run MCP server directly (test)
python -m src.main

# Run tests
pytest tests/ -m "not integration and not benchmark"
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- [Zed IDE](https://zed.dev/) — code editor
- [LM Studio](https://lmstudio.ai/) — local LLM inference
- [LanceDB](https://lancedb.github.io/) — vector database
- [Model Context Protocol](https://modelcontextprotocol.io/) — MCP standard
