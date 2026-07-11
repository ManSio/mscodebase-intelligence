<img src="logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](docs/en/CONTRIBUTING.md) • [🇷🇺 Русский](docs/ru/CONTRIBUTING.md) • [🇨🇳 中文](docs/zh/CONTRIBUTING.md)

# Contributing — MSCodeBase Intelligence

> **Please read the full guide in your language:**
> - [English](docs/en/CONTRIBUTING.md)
> - [Русский](docs/ru/CONTRIBUTING.md)
> - [中文](docs/zh/CONTRIBUTING.md)

---

## Quick Links

| Resource | Link |
|----------|------|
| Architecture | [ARCHITECTURE.md](docs/en/ARCHITECTURE.md) |
| Changelog | [CHANGELOG.md](docs/en/CHANGELOG.md) |
| Installation | [INSTALL.md](docs/en/INSTALL.md) |
| FAQ | [FAQ.md](docs/en/FAQ.md) |

---

## Project Overview

| Metric | Value |
|--------|-------|
| **Version** | 3.2.0 — Polyglot Graph Engine |
| **Tests** | 494 ✅ |
**MCP Tools** | 58 (41 class-based + 14 intel + 3 diagnostic) |
| **Parsing Languages** | 30 file extensions (16 with ASSIGNED_FROM data flow) |
| **PropertyGraph** | SQLite WAL — 3,337 ASSIGNED_FROM edges on MSCodeBase |

**Key modules:**

| Module | File | Purpose |
|--------|------|---------|
| PropertyGraph | `src/core/graph.py` | SQLite property graph — nodes, edges, JSON properties |
| SymbolIndex Adapter | `src/core/graph_adapter.py` | Wraps PropertyGraph as SymbolIndex (PURE mode) |
| Cypher Engine | `src/core/cypher_engine.py` | MATCH→SQL query translation |
| Unified Parser | `src/core/parser.py` | Tree-sitter AST + ASSIGNED_FROM extraction (16 languages) |
| Indexer | `src/core/indexer.py` | LanceDB vector storage + incremental cleanup |

---

## Quick Start

```bash
# Setup
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd MSCodeBase
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e "."

# Run tests
pytest tests/ -v

# Run dataflow experiment
python -m src.core.dataflow_experiment
```

See [docs/en/CONTRIBUTING.md](docs/en/CONTRIBUTING.md) for detailed guidelines.
