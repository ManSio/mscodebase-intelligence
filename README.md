<div align="center">

<img src="logo/baner.png" alt="MSCodeBase Banner" width="100%"/>

[🇬🇧 English](README.md) • [🇷🇺 Русский](docs/ru/README.md) • [🇨🇳 中文](docs/zh/README.md)

# MSCodebase Intelligence

**AI-powered semantic code search for Zed IDE — deep code analysis MCP server**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Zed](https://img.shields.io/badge/Zed-extension-orange.svg)](https://zed.dev/)
[![Tests](https://img.shields.io/badge/tests-406%20passing-brightgreen)](tests/)

[Features](#-features) • [Quick Start](#-quick-start) • [Tools](#-mcp-tools-50-total) • [Documentation](#-documentation-map) • [Installation](docs/en/INSTALL.md) • [Architecture](docs/en/ARCHITECTURE.md) • [Contributing](CONTRIBUTING.md) • [Security](SECURITY.md)

*Last updated: 2026-07-11*

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
│  │  · 50 tools for AI assistant                 │  │
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
| ✏️ **Inline autocomplete** | ❌ | ✅ |
| 🏷️ **Inlay hints** | ❌ | ✅ |

### Why not LSP

MSCodeBase **does not use LSP**. The LSP server (`src/lsp_main.py`) was an experimental part of the project and **does not work in Zed** due to architectural limitations of the editor itself (see [LSP_WONTFIX.md](docs/en/investigations/LSP_WONTFIX.md)).

Instead, all functionality is implemented through **50 MCP tools** available in Zed via the MCP protocol.

### Platforms

Designed and tested on **Windows**. macOS and Linux should work but have not been validated officially.

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔍 **Unified Search** | `search_code(query, mode, intent_hint)` — single tool: fast/quality/deep/context/ask/auto |
| 🧠 **Intelligence Layer** | 14 high-level `intel_*` tools: self-diagnostics, topology, memory, error prediction |
| 🗃️ **Project Memory** | ADR, known issues, tech debt — automatically persisted between sessions |
| 🌐 **Cross-repo Search** | Search across multiple projects with `@mention` syntax |
| 🌳 **Call Graph** | Full call graph: definition + callers + callees + impact analysis |
| 🏗 **Structural Search** | 13 AST patterns (class_inheritance, async_function, decorator, etc.) |
| 🔎 **Context Search** | Find similar code — paste a fragment, get semantic duplicates |
| 🪣 **Multi-Bucket RAG** | Code/docs buckets, soft weighting, intent_hint (code/docs/auto) |
| 🤖 **mode=ask** | RAG answer generation via phi-4 (server profile) |
| 💾 **LanceDB v2** | Vector DB with per-project isolation (incremental BM25 reindex) |
| 🛡 **Rate Limiting** | DebounceBatch + CircuitBreaker — protection against VFS loops |
| 🏥 **Self-Diagnosis** | `get_health_report` + `index_health` — full check and recovery |
| 🧪 **Clean Architecture** | DI Container (15 services), 56 tools (39 class-based + 14 intel + 3 diag), 406+ tests |
| 🪟 **Multi-Window** | `ProjectIndexerRegistry` — isolated Indexer per project, LRU 5, ResourceMonitor throttle |
| ✏️ **Write Tools** | 6 tools: rename/move/delete/replace symbols with preview/apply + `@modification_guard` |
| ⚡ **Meta-Patching** | LanceDB `move_chunks_metadata` — file_path rename without re-embedding (50ms vs 5s) |
| ⚙️ **SYSTEM_PROFILE** | `light` (sync) / `server` (async with phi-4) |

---

## 🚀 Quick Start

Install the `mscodebase-intelligence` extension in Zed, then:

```bash
cd D:\Project\MSCodeBase
python install.py

# Restart Zed (File → Quit → reopen)
# Verify: intel_get_runtime_status()
```

**install.py does:**
1. Copies 39+ source files to the extension directory
2. Installs Python dependencies
3. Downloads llama-server.exe + GGUF models (bge-m3 embed + reranker)
4. Configures MCP in Zed's settings.json

See also: [AI_INSTALLATION_PROMPT.md](AI_INSTALLATION_PROMPT.md), [docs/en/INSTALL.md](docs/en/INSTALL.md)

### Providers

MCP auto-selects the best available provider:

```
llama.cpp GGUF (GPU) → ONNX Runtime (CPU) → LM Studio (if running) → BM25 only
   ~1.0 GB RAM           ~1.7 GB RAM          ~6 GB RAM             no embeddings
   2× llama-server       in-process ONNX       external API
```

Benchmarks: [docs/research/2026-07-10-final-benchmark.md](docs/research/2026-07-10-final-benchmark.md)

---

## 📚 Documentation Map

| Document | Description | Audience | Languages |
|----------|-------------|----------|-----------|
| **[docs/en/INSTALL.md](docs/en/INSTALL.md)** | Installation, setup, uninstall | Users | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/ARCHITECTURE.md](docs/en/ARCHITECTURE.md)** | Clean Architecture, Layers, DI | Developers | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/ARCHITECTURE_DEEP.md](docs/en/ARCHITECTURE_DEEP.md)** | Deep architecture: pipeline, lifecycle, comparison | Architects | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/SEARCH_PIPELINE.md](docs/en/SEARCH_PIPELINE.md)** | Search pipeline: BM25 → RRF → Reranker | Developers | 🇬🇧 |
| **[docs/en/GRACEFUL_DEGRADATION.md](docs/en/GRACEFUL_DEGRADATION.md)** | 5 levels of graceful degradation (llama.cpp → ONNX → BM25) | DevOps | 🇬🇧 |
| **[docs/en/ARCHITECTURE_LAYERS.md](docs/en/ARCHITECTURE_LAYERS.md)** | 10 runtime layers | Architects | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/FAQ.md](docs/en/FAQ.md)** | Frequently Asked Questions | All | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/TELEMETRY.md](docs/en/TELEMETRY.md)** | Metrics, ETA, data collection | DevOps | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/investigations/ONNX_SESSION_REPORT.md](docs/en/investigations/ONNX_SESSION_REPORT.md)** | Full ONNX migration, 7 fixes, benchmarks | Support | 🇬🇧 |
| **[docs/en/investigations/LSP_WONTFIX.md](docs/en/investigations/LSP_WONTFIX.md)** | LSP on Windows investigation (WONTFIX) | Support | 🇬🇧 🇨🇳 |
| **[docs/en/ZED_WINDOWS_QUIRKS.md](docs/en/ZED_WINDOWS_QUIRKS.md)** | Windows specifics, Restricted Mode | Windows users | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/CHANGELOG.md](docs/en/CHANGELOG.md)** | Version history | All | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/CONTRIBUTING.md](docs/en/CONTRIBUTING.md)** | How to contribute, PRs | Contributors | 🇬🇧 🇷🇺 🇨🇳 |
| **[docs/en/SECURITY.md](docs/en/SECURITY.md)** | Security policy, vulnerabilities | Security | 🇬🇧 🇷🇺 🇨🇳 |
| **[AGENTS.md](AGENTS.md)** | AI Agent system rules | AI Agent | 🇬🇧 |
| **[SECURITY.md](SECURITY.md)** | Security policy, reporting vulnerabilities | Security | 🇬🇧 |
| **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** | Community standards | Contributors | 🇬🇧 |

| **[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)** | Known issues & technical debt registry | All | 🇬🇧 |

All documents are cross-referenced. Available in 3 languages: English, Русский, 中文.

---

## 🔧 MCP Tools (56 total)

### Core Search

| Tool | When to Use |
|------|-------------|
| `search_code(query, mode, filter_layer, intent_hint)` | **Main search tool.** `mode="auto"` / `"fast"` / `"quality"` / `"deep"` / `"context"` / `"ask"`. `intent_hint="code"` / `"docs"` / `"auto"` — soft bucket weighting. `filter_layer="core"` — search within specific architecture layer |
| `structural_search(pattern)` | AST search: `class_inheritance`, `async_function`, `function_with_decorator` and more |
| `cross_repo_search(query @repo)` | Search across multiple projects (mono-repo) |
| `cross_project_deps(action)` | Cross-project dependency graph: `graph` / `deps` / `cycles` / `impact` |
| `get_symbol_info(query)` | Call Graph: callers, callees, impact files |
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
| `watcher_status()` | Component status: embedder mode, indexing, health |
| `get_logs(project_root)` | Latest errors and warnings from project logs |
| `get_repo_map(project_root)` | Project map: file tree + key symbols |
| `read_live_file(path)` | Read file from LSP memory (including unsaved changes) |
| `predict_eta(operation)` | Predict operation duration based on history |
| `run_health_check()` | Full project health check (tests + git + index) |

### Analytics

| Tool | When to Use |
|------|-------------|
| `get_hotspots(project_root)` | Hotspots — files with high bug rate |
| `get_repo_rank(project_root, top_k)` | Symbol importance ranking (PageRank on call graph) |
| `get_bug_correlation(project_root)` | Bug-change correlation analysis |
| `get_related_files(project_root, path)` | Files related via co-change / bug correlation |
| `graph_query(query_type, target)` | Knowledge graph queries: `impact` / `feature` / `deps` / `tests` |
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

### Write Tools (7)

| Tool | When to Use |
|------|-------------|
| `rename_symbol(old, new, apply)` | Rename symbol across all files (preview/apply, collision check) |
| `move_symbol(symbol, to_file, apply)` | Move symbol to another file (preview/apply, import updates) |
| `safe_delete(symbol, force, apply)` | Safe delete with reference check (force mode) |
| `replace_symbol(symbol, new_code, apply)` | Replace function/class body (preview/apply) |
| `insert_before_symbol(anchor, new_code, apply)` | Insert code before anchor symbol (preview/apply) |
| `insert_after_symbol(anchor, new_code, apply)` | Insert code after anchor's body (preview/apply) |
| `ack_impact(file_path)` | Acknowledge impact for modification guard |

### Intelligence Layer (intel_*) — 14 High-Level Tools

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
| `intel_tool_health()` | Tool success rates, latency, confidence |
| `intel_explain_project_state(root)` | Human-readable project state diagnosis |
| `intel_get_project_context(root)` | Single snapshot: state, index, health, memory |

### Diagnostic Tools (3)

| Tool | What it does |
|------|-------------|
| `debug_runtime_passport()` | Process passport: RUN_ID, PID, build info |
| `get_runtime_counters()` | Runtime counters: calls, blocks, warnings |
| `intel_execution_timeline(limit)` | Recent action timeline with durations |

---

## 🏗️ Architecture

### Clean Architecture with DI Container

```
┌──────────────────────────────────────────────────────────────────┐
│                   MCP Server (~220 lines)                        │
│            src/mcp/server.py — registration only                │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              DI Container (15 services)                   │   │
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
│  39 Tool Classes   │  │  14 intel_* tools + 3 diag      │
│  │  src/mcp/tools/*.py │  │  src/core/intelligence_layer.py    │  │
│  │  One class per tool  │  │  error_boundary decorator          │
│  │  Constructor Inj.   │  │  JSON status/message/detail        │  │
│  │  Constructor Inj.   │  │  asyncio.wait_for(timeout)        │  │
│  └────────────────────┘  └────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐     ┌───────────────────┐
│  RemoteEmbedder  │     │  LanceDB v2       │
│  (LM Studio /    │     │  (Vector DB)       │
│   Ollama / ONNX) │     │  BM25 + Vector    │
└─────────────────┘     └───────────────────┘
```

---

## ⚡ Performance

| Mode | Latency | Best For |
|:-----|:--------|:---------|
| `search_code(query, mode="fast")` | ~300ms | Simple keyword / exact name |
| `search_code(query, mode="quality")` | ~1200ms | Semantic search with reranker |
| `search_code(query, mode="deep")` | ~2-5s | Complex research across modules |
| `search_code(query, mode="context")` | ~500ms | Find similar code by fragment |
| `cross_repo_search(query @repo)` | ~500ms-2s | Cross-project search |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LM_STUDIO_URL` | `http://localhost:1234/v1` | LM Studio API endpoint |
| `LM_STUDIO_PORT` | `1234` | LM Studio port |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `LOG_LEVEL` | `INFO` | Logging verbosity level |
| `ZED_WINDOWS_QUIRKS.md` | *(see file)* | Windows-specific instructions |

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
│   ├── main.py                   # MCP server entry point (~220 lines)
│   ├── lsp_main.py               # LSP server (DI-based, for didSave indexing)
│   ├── mcp/
│   │   ├── server.py             # DI routing — only imports + registration
│   └── tools/                 # 10 files, 33 class-based tools
│   │       ├── search_tools.py   # search_code, get_symbol_info, impact_analysis
│   │       ├── indexing_tools.py # notify_change, index_project_dir, index_health
│   │       ├── git_tools.py      # get_branch_info, get_commit_history
│   │       ├── system_tools.py   # get_index_status, watcher_status, read_live_file
│   │       ├── analysis_tools.py # structural_search, get_repo_map, scan_changes
│   │       ├── graph_tools.py    # cross_repo_search, graph_query, get_related_files
│   │       ├── investigation_tools.py  # get_bug_correlation, get_hotspots
│   │       └── lifecycle_tools.py      # submit_background_task, verify_action
│   ├── core/
│   │   ├── di_container.py       # ★ DI Container (15 services, ServiceCollection)
│   │   ├── error_handler.py      # ★ error_boundary + ToolError
│   │   ├── rate_limiter.py       # ★ SlidingWindowRateLimiter + DebounceBatch + CircuitBreaker
│   │   ├── indexer.py            # LanceDB vector storage
│   │   ├── searcher.py           # Hybrid search (BM25 + Dense + RRF)
│   │   ├── symbol_index.py       # Call Graph (BFS, impact analysis)
│   │   ├── intelligence_layer.py # intel_* tools (14 high-level)
│   │   ├── llama_runner.py       # llama.cpp lifecycle manager ★
│   │   ├── remote_embedder.py    # LM Studio / Ollama / llama.cpp / ONNX client
│   │   ├── reranker.py           # Multi-Provider Reranker (HTTP to providers)
│   │   ├── parser.py             # Tree-sitter AST
│   │   ├── health_report.py      # Self-diagnosis engine
│   │   └── ...
│   └── utils/
│       ├── paths.py              # SafePathManager, to_win_long_path
│       └── zed_config.py         # Auto-configure Zed settings
├── docs/
│   ├── en/               # English docs
│   ├── ru/               # Russian docs
│   └── zh/               # Chinese docs
├── tests/                        # 406 tests (pytest)
├── .agents/skills/               # Skills for AI agent
├── install.py                    # Installer
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
