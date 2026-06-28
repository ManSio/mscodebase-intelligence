<div align="center">

# MSCodebase Intelligence

**AI-powered semantic code search for Zed IDE viaPython 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-160%20passed-brightgreen.svg)]()
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
| 🌳 **Call Graph** | Bidirectional BFS (depth 2+): callers, callees, call chains, impact analysis |
| 🔧 **Structural Search** | 13 AST patterns (class_inheritance, decorator, async, etc.) |
| 🔎 **Context Search** | Find similar code by embedding selected fragment |
| ⚡ **LSP + MCP Hybrid** | Single-process architecture: LSP for indexing, MCP for AI tools |
| 💾 **LanceDB v2** | Local vector storage with per-project isolation |
| 🧠 **In-Memory Indexing** | Reads from LSP VFS (no disk delay on Windows) |

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

### Configure Zed

Add to your project's `.zed/settings.json` (or let `install.py` do it):

```json
{
  "lsp": {
    "mscodebase-lsp": {
      "command": ".venv/Scripts/python.exe",
      "arguments": ["-u", "src/hybrid_server.py"]
    }
  },
  "context_servers": {
    "mscodebase-mcp": {
      "url": "http://127.0.0.1:8765/sse"
    }
  },
  "languages": {
    "Python": { "language_servers": ["mscodebase-lsp"] },
    "TypeScript": { "language_servers": ["mscodebase-lsp"] },
    "Rust": { "language_servers": ["mscodebase-lsp"] }
  },
  "autosave": "on_focus_change"
}
```

> **Note:** `autosave: "on_focus_change"` ensures files are saved when switching tabs, triggering LSP indexing.

### Use in Zed

1. Restart Zed IDE
2. Open your project
3. Indexing starts automatically (LSP cold start)
4. Edit files → instant re-indexing via LSP
5. Use `@mscodebase-intelligence` MCP tools in chat

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

## ⚡ Performance Tuning

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

### Zed Settings

Recommended `.zed/settings.json` for optimal performance:

```json
{
  "autosave": "on_focus_change",
  "format_on_save": "on",
  "tab_size": 4,
  "languages": {
    "Python": {
      "language_servers": ["mscodebase-lsp"],
      "format_on_save": "on",
      "tab_size": 4
    }
  }
}
```

> **Why `autosave: "on_focus_change"`?**
> Zed with `autosave: "off"` (default) doesn't write to disk immediately on Ctrl+S.
> This setting ensures files are saved when switching tabs, triggering LSP indexing.

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

## 🏗️ Architecture

### Hybrid LSP + MCP (Single Process)

```
┌─────────────────────────────────────────────────────────────┐
│                    Hybrid Server (src/hybrid_server.py)      │
│                                                             │
│  ┌─────────────────────┐    ┌─────────────────────────┐    │
│  │   LSP Server (stdio) │    │   MCP Server (HTTP/SSE) │    │
│  │                      │    │                         │    │
│  │  Receives from Zed:  │    │  Provides tools for AI: │    │
│  │  - didOpen           │    │  - search_code          │    │
│  │  - didChange         │    │  - get_index_status     │    │
│  │  - didSave           │    │  - read_live_file       │    │
│  │  - didClose          │    │  - ...                  │    │
│  └──────────┬───────────┘    └───────────┬─────────────┘    │
│             │                            │                  │
│             └────────────┬───────────────┘                  │
│                          │                                  │
│                   ┌──────▼──────┐                           │
│                   │  Shared     │                           │
│                   │  Indexer    │                           │
│                   │  (LanceDB)  │                           │
│                   └─────────────┘                           │
└─────────────────────────────────────────────────────────────┘
```

### Why Hybrid?

| Problem | Old (Separate Processes) | New (Hybrid) |
|---------|--------------------------|--------------|
| WinError 5 (file locks) | ❌ Conflicts between LSP & MCP | ✅ Single process, no conflicts |
| Disk write delay on Windows | ❌ `didSave` before physical write | ✅ Read from LSP VFS memory |
| AI edits to closed files | ❌ Not detected | ✅ `didOpen`/`didChange`/`didClose` |
| Memory usage | ❌ Two Python processes | ✅ One process, shared state |

### Components

```
MSCodebase Intelligence
├── Hybrid Server (src/hybrid_server.py)     ← LSP + MCP in one process
│   ├── LSP Handler (stdio)                 ← Receives events from Zed
│   ├── MCP Handler (HTTP/SSE :8765)        ← Provides tools for AI
│   └── SharedIndexer                       ← Single LanceDB instance
├── Core Engine (src/core/)
│   ├── indexer.py          — LanceDB vector storage + file scanning
│   ├── searcher.py         — Hybrid search (BM25 + Dense + RRF)
│   ├── remote_embedder.py  — LM Studio / Ollama embeddings
│   ├── parser.py           — Tree-sitter AST parsing
│   ├── reranker.py         — Multi-Provider Reranker (Ollama/LM Studio)
│   └── ...
└── Legacy (src/lsp_main.py, src/mcp/server.py)  ← Kept for reference
```

### Data Flow

```
Zed IDE ──stdio──→ LSP Server ──→ SharedIndexer ──→ LanceDB
   │                                           ↑
   └──HTTP/SSE──→ MCP Server ──────────────────┘
                      ↓
               AI Assistant Tools
                      ↓
               RemoteEmbedder → LM Studio (embeddings)
                      ↓
               MultiProviderReranker (Ollama → LM Studio)
                      ↓
               Results → Zed IDE
```

### LSP Events Handled

| Event | When | Action |
|-------|------|--------|
| `didOpen` | File opened (including background for AI) | Index from memory |
| `didChange` | Text changed (including AI edits) | Re-index from memory |
| `didSave` | Ctrl+S pressed | Re-index from memory (not disk!) |
| `didClose` | File closed (buffer flushed to disk) | Final index from disk |
| `didChangeWatchedFiles` | External changes (git, etc.) | Re-index from disk |

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

## 🔧 Troubleshooting

### LSP Server Not Starting

**Symptoms:** No `[LSP DID_*]` logs when editing files.

**Checklist:**
1. Verify `.zed/settings.json` exists in project root
2. Check `command` path points to correct Python interpreter
3. Check Zed logs: `%LOCALAPPDATA%\Zed\logs\Zed.log`
4. Try running LSP manually:
   ```bash
   python -u src/hybrid_server.py < /dev/null
   ```

### Files Not Indexing on Save

**Symptoms:** Changes not reflected in search results.

**Solutions:**
1. Set `"autosave": "on_focus_change"` in `.zed/settings.json`
2. Switch tabs after editing (triggers autosave)
3. Check LSP logs: `.codebase_indices/logs/<project>.log`

### WinError 5 (Permission Denied)

**Symptoms:** `PermissionError` when reading/writing files.

**Cause:** Multiple processes accessing LanceDB simultaneously.

**Solution:** Use Hybrid server (single process) instead of separate LSP + MCP.

### MCP Tools Not Available

**Symptoms:** AI assistant can't call `search_code` etc.

**Check:**
1. MCP server running on port 8765: `netstat -an | findstr 8765`
2. `context_servers.url` points to `http://127.0.0.1:8765/sse`
3. Restart Zed after config changes

### Cold Start (First Indexing)

**Symptoms:** Search returns empty results.

**Solution:** Wait for cold start to complete:
```
Check logs: "Cold start complete"
Or call: get_index_progress()
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

### Run Hybrid Server Manually

```bash
# LSP mode (for testing — will exit without Zed connection)
python -u src/hybrid_server.py < /dev/null

# MCP server runs automatically on http://127.0.0.1:8765/sse
# Test with curl:
curl http://127.0.0.1:8765/sse
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
├── tests/                         # 153 unit tests
│   ├── test_agentic_search.py     # 25 tests
│   ├── test_reranker.py           # 20 tests (Multi-Provider Reranker)
│   ├── test_symbol_index_call_graph.py # 22 tests (Call Graph BFS)
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

## 📝 Changelog

### v2.0.0 (2026-06-28) — Hybrid Architecture

**Breaking Changes:**
- New entry point: `src/hybrid_server.py` (replaces `lsp_main.py` + `mcp/server.py`)
- MCP now runs via HTTP/SSE on port 8765 (not stdio)
- Requires `.zed/settings.json` update

**New Features:**
- ⚡ **Hybrid LSP + MCP** — single process, shared memory
- 🧠 **In-Memory Indexing** — reads from LSP VFS (no disk delay on Windows)
- 🔄 **Full Document Sync** — receives complete file content via `didChange`
- 🛡️ **No WinError 5** — single process eliminates file lock conflicts
- 🤖 **AI Edit Detection** — catches `didOpen`/`didChange`/`didClose` for background edits

**Technical Details:**
- LSP events: `didOpen`, `didChange`, `didSave`, `didClose`, `didChangeWatchedFiles`
- MCP server: FastMCP with SSE transport on `http://127.0.0.1:8765/sse`
- SharedIndexer: single LanceDB instance accessible by both LSP and MCP
- Cold start: automatic full indexing on LSP initialization

**Migration:**
1. Update `.zed/settings.json` (see Configuration section)
2. Restart Zed
3. Old `lsp_main.py` and `mcp/server.py` kept for reference

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
