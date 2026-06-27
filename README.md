# MSCodeBase Intelligence

**Enterprise-grade code search and analysis extension for Zed IDE.**

## ✨ Key Features

- **Hybrid Search**: Vector embeddings (LM Studio) + lexical BM25 + Tree-sitter structural analysis
- **Semantic Chunking**: AST-based code segmentation preserving structure
- **Call Graph Analysis**: Find definitions, callees, and impact scope for any symbol
- **Architectural Diff**: Track changes and their impact across the codebase
- **Real-time Indexing**: LSP-powered incremental updates on file save
- **Windows Native**: Full Windows support with path normalization (no Docker, no WSL)

## 📋 Quick Start

### Prerequisites

- **Zed Editor** (latest version)
- **Python 3.10+**
- **LM Studio** (recommended) or Ollama for embeddings

### Installation

```powershell
# Clone repository
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd MSCodeBase

# Run installer (copies extension, creates venv, configures Zed)
python install.py
```

After installation:
1. Launch LM Studio and enable the embedding server (port 1234)
2. Restart Zed IDE
3. Open your project — indexing starts automatically

### Usage

Use the `@mscodebase-intelligence` MCP tools in Zed chat:

| Tool | When to Use |
|------|-------------|
| `get_index_status` | Check if project is indexed |
| `index_project_dir` | Force full re-indexing |
| `search_code` | Semantic search by concept |
| `deep_search` | Iterative search with query refinement |
| `cross_repo_search` | Search across multiple indexed projects (use @-mentions) |
| `get_context` | Gather relevant code chunks |
| `get_symbol_info` | Find definition + call graph |
| `get_repo_map` | Project structure overview |
| `scan_changes` | Detect changes made outside Zed |
| `context_search` | Find similar code by fragment |
| `structural_search` | Search by AST patterns |
| `watcher_status` | Check system health |
| `get_logs` | Check project error logs |

## 🏗️ Architecture

```
MSCodeBase Intelligence
├── MCP Server (src/mcp/server.py)
│   ├── Tools: search_code, deep_search, cross_repo_search, get_context, get_symbol_info,
│   │         scan_changes, context_search, structural_search, get_logs, watcher_status
│   └── Prompts: mscodebase-rules (system rules for AI agent)
├── LSP Server (src/lsp_main.py)
│   └── Auto-indexes on file save
└── Core Engine (src/core/)
    ├── indexer.py          — LanceDB vector storage + file scanning
    ├── searcher.py         — Hybrid search (BM25 + Dense + RRF) + Agentic Deep Search
    ├── multi_project_searcher.py — Cross-repo search with @-mention syntax
    ├── symbol_index.py     — Tree-sitter symbol definitions + call graph
    ├── context_engine.py   — Compressed context generation
    ├── query_expansion.py  — Synonym expansion + stemming
    ├── structural_search.py — AST pattern matching (13 patterns)
    ├── remote_embedder.py  — LM Studio / Ollama / ONNX embeddings
    ├── parser.py           — Tree-sitter AST parsing
    ├── file_guard.py       — Security filtering + gitignore
    ├── gitignore_parser.py — Pattern matching
    ├── reranker.py         — Result reranking with relevance factor
    ├── log_manager.py      — File logging with rotation (2MB × 3)
    ├── integrity.py        — Merkle Tree change detection
    └── content_cache.py    — File hash caching
```

### Data Storage

Vector indexes are isolated per project in:
```
<PARENT_DIR>/.codebase_indices/lancedb_v2/index_<project>_<hash>.db
```

## ⚙️ Configuration

### Zed Settings (auto-configured by `install.py`)

```json
{
  "context_servers": {
    "mscodebase-intelligence": {
      "command": "python",
      "args": ["D:/Path/To/MSCodeBase/src/main.py"]
    }
  },
  "lsp": {
    "mscodebase-lsp": {
      "command": "python",
      "args": ["-u", "D:/Path/To/MSCodeBase/src/lsp_main.py"]
    }
  },
  "agent": {
    "system_prompt": "MSCodeBase Core Rules: ..."
  }
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `LM_STUDIO_HOST` | `127.0.0.1` | LM Studio host |
| `LM_STUDIO_PORT` | `1234` | LM Studio port |

## 🛠️ Development

### Setup

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Running Tests

```powershell
pytest tests/ -v
```

### Running MCP Server Manually

```powershell
python -m src.main
```

## 📁 Project Structure

```
MSCodeBase/
├── src/
│   ├── main.py                    # MCP entry point
│   ├── lsp_main.py                # LSP server entry
│   ├── core/                      # Core engine modules
│   ├── mcp/                       # MCP server + tools
│   └── utils/                     # Path management, zed config
├── tests/                         # Test suite
├── install.py                     # Deployment script
├── installers/                    # Build scripts
├── .agents/skills/                # Zed agent skills
├── pyproject.toml                 # Project metadata
├── requirements.txt               # Dependencies
├── README.md                      # This file
├── ARCHITECTURE.md                # Technical deep-dive
├── CHANGELOG.md                   # Version history
├── TESTING.md                     # QA scenarios
├── SECURITY.md                    # Security policy
└── AI_PROMPT.md                   # AI assistant instructions
```

## 📄 License

MIT License. See `LICENSE` for details.
