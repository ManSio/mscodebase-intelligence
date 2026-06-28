<div align="center">

# MSCodebase Intelligence

**AI-powered semantic code search for Zed IDE viaPython 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-138%20passed-brightgreen.svg)]()
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)

[Features](#-features) • [Quick Start](#-quick-start) • [Architecture](#-architecture) • [Performance](#-performance-tuning) • [Benchmarks](#-benchmarks)

</div>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔍 **Hybrid Search** | Vector embeddings (LM Studio) + lexical BM25 + Multi-Provider Reranking (Ollama/LM Studio) |
| 🧠 **Agentic Code Search** | Auto-decomposes complex queries → parallel sub-searches → Call Graph analysis → RRF aggregation |
| 🔄 **Agentic Deep Search** | Iterative search with query refinement across multiple passes |
| 🌐 **Cross-repo Search** | Search across multiple indexed projects with `@mention` syntax |
| 📊 **Progress Tracking** | Real-time indexing progress with phase, percent, files done/total |
| 🌳 **Call Graph** | Find definitions, callees, and impact scope for any symbol |
| � **Structural Search** | 13 AST patterns (class_inheritance, decorator, async, etc.) |
| � **Context Search** | Find similar code by embedding selected fragment |
| � **LSP Integration** | Auto-index on file save |
| 💾 **LanceDB v2** | Local vector storage with per-project isolation |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+**
- **Zed IDE** ([download](https://zed.dev/))
- **LM Studio** (recommended) or Ollama for embeddings + reranking

### Install

```bash
# Clone repository
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence

# Run installer (copies extension, creates venv, configures Zed)
python install.py
```

### Start LM Studio

1. Download [LM Studio](https://lmstudio.ai/)
2. Load embedding model: `text-embedding-bge-m3` (1024 dim)
3. Start server (default port: 1234)

### Optional: Enable LLM Reranking (Ollama / LM Studio)

For enhanced search relevance, run an instruct model:

```bash
# Option A: Ollama (recommended — specialized reranker)
ollama run bge-reranker-v2-m3

# Option B: LM Studio — load any instruct model (e.g. Qwen2.5-7B-Instruct)
```

When available, the reranker reorders search results via a single batch LLM call.
If neither is running, search works normally with RRF ranking (graceful fallback).

### Use in Zed

1. Restart Zed IDE
2. Open your project
3. Indexing starts automatically
4. Use `@mscodebase-intelligence` MCP tools in chat

---

## � Tools (14 total)

| Tool | When to Use |
|------|-------------|
| `get_index_status` | Check if project is indexed |
| `get_index_progress` | Check indexing progress (phase, percent) |
| `index_project_dir` | Force full re-indexing |
| `search_code` | Semantic search by concept |
| `search_code(agentic=True)` | Complex multi-part queries |
| `deep_search` with refinement |
| `cross_repo_search` | Multi-project search (`query @backend @frontend`) |
| `get_context` | Gather relevant code chunks |
| `get_symbol_info` | Find definition + call graph |
| `get_repo_map` | Project structure overview |
| `scan_changes` | Detect changes made outside Zed |
| `context_search` | Find similar code by fragment |
| `structural_search` | Search by AST patterns |
| `watcher_status` | Check system health |
| `get_logs` | Check project error logs |

---

## � Performance Tuning

### Search Modes

| Mode | When | Latency | Accuracy |
|:---|:---|:---|:---:|
| `search_code(query)` | Simple, single concept | ~100ms | High |
| `search_code(agentic=True)` | Complex (2+ concepts) | ~300-500ms | Very High |
| `deep_search(query)` | Research tasks | ~1-3s | Highest |
| `cross_repo_search(query @repo)` | Multi-project | ~500ms-2s | High |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LM_STUDIO_URL` | `http://localhost:1234/v1` | LM Studio API endpoint |
| `LM_STUDIO_PORT` | `1234` | LM Studio port |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## � Benchmarks

```bash
pytest tests/benchmark_agentic_search.py -v -m benchmark
```

| Query Type | Hybrid | Agentic | Winner |
|:---|:---|:---|:---:|
| Simple (1 concept) | ~50ms | ~150ms | Hybrid |
| Complex (3+ concepts) | ~100ms | ~300ms | Agentic |
| Cross-project | N/A | ~500ms | Cross-repo |

---

## �️ Architecture

```
MSCodebase Intelligence
├── MCP Server (src/mcp/server.py)
│   ├── 14 Tools: search_code, deep_search, cross_repo_search, get_context,
│   │            get_symbol_info, get_repo_map, scan_changes, context_search,
│   │            structural_search, get_logs, watcher_status, get_index_status,
│   │            get_index_progress, index_project_dir
│   └── Prompts: mscodebase-rules (system rules for AI agent)
├── LSP Server (src/lsp_main.py)
│   └── Auto-indexes on file save
└── Core Engine (src/core/)
    ├── indexer.py          — LanceDB vector storage + file scanning + progress callback
    ├── searcher.py         — Hybrid search (BM25 + Dense + RRF) + Agentic Deep Search
    ├── multi_project_searcher.py — Cross-repo search with @-mention syntax
    ├── symbol_index.py     — Tree-sitter symbol definitions + call graph
    ├── context_engine.py   — Compressed context generation
    ├── query_expansion.py  — Synonym expansion + stemming
    ├── structural_search.py — AST pattern matching (13 patterns)
        ├── remote_embedder.py  — LM Studio / Ollama embeddings
        ├── parser.py           — Tree-sitter AST parsing
        ├── file_guard.py       — Security filtering + gitignore
        ├── gitignore_parser.py — Pattern matching
        ├── reranker.py         — Multi-Provider Reranker (Ollama/LM Studio) + legacy BM25+dense
    ├── log_manager.py      — File logging with rotation (2MB × 3)
    ├── integrity.py        — Merkle Tree change detection
    └── content_cache.py    — File hash caching
```

### Data Flow

```
Zed IDE → MCP Server → RemoteEmbedder → LM Studio (embeddings)
                ↓
           Indexer (LanceDB)
                ↓
           Searcher (BM25 + Vector + RRF)
                ↓
           MultiProviderReranker (Ollama :11434 → LM Studio :1234)
                ↓
           Results → Zed IDE
```

### Multi-Provider Reranking

After RRF fusion, results can be reranked by an external LLM:

```
[Recall (BM25 + Dense)] → [Top-20 RRF] → [MultiProviderReranker]
                                                │
                    ┌───────────────────────────┴───────────────────────────┐
              (Ollama available?)                                 (LM Studio available?)
                    │                                                     │
          [Ollama /api/chat batch]                            [LM Studio /v1/chat batch]
                    │                                                     │
                    └───────────────────────────┬───────────────────────────┘
                                                ▼
                                      [Sort by LLM scores] → [ZED Chat]
```

**Priority:** Ollama (specialized rerankers) → LM Studio (instruct models) → RRF fallback

### Storage

Vector indexes are isolated per project:
```
<PROJECT_ROOT>/.codebase_indices/lancedb_v2/index_<project>_<hash>.db
```

---

## 🛠️ Development

### Setup

```bash
# Clone
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence

# Create venv
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### Run Tests

```bash
# All tests
pytest tests/ -v

# Without slow tests
pytest tests/ -m "not slow" -v

# Only benchmarks
pytest tests/benchmark_agentic_search.py -v -m benchmark
```

### Run MCP Server Manually

```bash
python -m src.main
```

### Code Quality

```bash
# Format
black src/ tests/
isort src/ tests/

# Check
black --check src/ tests/
isort --check-only src/ tests/
```

---

## 📁 Project Structure

```
MSCodeBase/
├── src/
│   ├── main.py                    # MCP entry point
│   ├── lsp_main.py                # LSP server entry
│   ├── core/                      # Core engine modules
│   │   ├── indexer.py             # LanceDB + progress callback
│   │   ├── searcher.py            # Hybrid search + agentic
│   │   ├── multi_project_searcher.py
│   │   ├── symbol_index.py        # Call Graph
│   │   ├── context_engine.py
│   │   ├── query_expansion.py
│   │   ├── structural_search.py   # 13 AST patterns
│   │   ├── remote_embedder.py     # LM Studio/Ollama
│   │   ├── parser.py
│   │   ├── file_guard.py
│   │   ├── gitignore_parser.py
│   │   ├── reranker.py            # Multi-Provider Reranker (Ollama/LM Studio)
│   │   ├── log_manager.py
│   │   ├── integrity.py
│   │   └── content_cache.py
│   ├── mcp/                       # MCP server + tools
│   │   └── server.py              # 14 MCP tools + prompts
│   └── utils/
│       ├── paths.py
│       └── zed_config.py
├── tests/                         # 131 unit tests
│   ├── test_agentic_search.py     # 25 tests
│   ├── test_reranker.py           # 20 tests (Multi-Provider Reranker)
│   ├── test_deep_search.py        # 15 tests
│   ├── test_cross_repo_search.py  # 21 tests
│   ├── test_index_progress.py     # 11 tests
│   ├── test_searcher.py           # 4 tests
│   ├── test_indexer_project_path.py # 6 tests
│   ├── test_multi_project_query_expansion.py # 25 tests
│   ├── test_embedder.py           # 6 tests
│   ├── test_parser.py             # 4 tests
│   ├── test_connection.py         # 1 test
│   ├── test_mutation_core.py      # 3 tests
│   └── test_automation.py         # 1 test
├── benchmark_agentic_search.py    # 7 benchmark tests
├── scripts/
│   └── full_index.py              # Full indexing script
├── install.py                     # Cross-platform installer
├── .agents/skills/                # Zed agent skills
│   └── mscodebase-rules/SKILL.md
├── pyproject.toml
├── requirements.txt
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
├── TESTING.md
├── CONTRIBUTING.md
└── SECURITY.md
```

---

## 🔒 Security

- **Local-only storage** — all data stored locally (no cloud)
- **Path hashing** — project isolation via path hashing
- **Gitignore filtering** — respects .gitignore patterns
- **File guard** — security filtering + binary detection
- **No elevated permissions** — runs as regular user

See [SECURITY.md](SECURITY.md) for details.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make changes following code standards
4. Run tests: `pytest tests/ -v`
5. Commit: `feat(module): add amazing feature`
6. Push and create PR

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## � License

MIT License. See [LICENSE](LICENSE) for details.

---

## 🔗 Links

- **Repository**: https://github.com/ManSio/mscodebase-intelligence
- **Issues**: https://github.com/ManSio/mscodebase-intelligence/issues
- **LM Studio**: https://lmstudio.ai/
- **Zed IDE**: https://zed.dev/
- **MCP Protocol**: https://modelcontextprotocol.io/

---

<div align="center">

Built with ❤️ for the Zed community

</div>
