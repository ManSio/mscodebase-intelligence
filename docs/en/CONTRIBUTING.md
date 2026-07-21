<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](CONTRIBUTING.md) • [🇷🇺 Русский](../ru/CONTRIBUTING.md) • [🇨🇳 中文](../zh/CONTRIBUTING.md)

# Contributing — MSCodeBase Intelligence

> **Version:** 3.3.9 — DocSync Edition

---

## 1. Setup

```powershell
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd MSCodeBase
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e "."
```

Requirements: Python 3.10+, Windows (primary) or Linux (experimental).

---

## 2. Architecture (Clean Architecture)

```
src/
├── main.py              # Entry point (minimal)
├── mcp/
│   ├── server.py        # MCP server registration (~220 lines)
│   ├── server_factory.py # Server factory + DI setup
│   ├── server_tools.py  # Tool registration (42 tools total)
│   └── tools/           # 14 files, 18 core + 13 intel + 7 inline + 3 dev + 1 optional
│       ├── base.py          # MCPTool ABC
│       ├── search_tools.py  # search_code, get_symbol_info, impact_analysis
│       ├── codebase_tool.py # codebase(action={rename,move,delete,...})
│       ├── write_tools.py   # write(action={rename,move,delete,replace,insert,impact})
│       ├── graph_tools.py   # graph_query, cross_repo_search, cross_project_deps
│       ├── indexing_tools.py# index management
│       ├── git_tools.py     # git(action={log,history,branch})
│       ├── doc_tools.py     # generate_docs, bump_version, auto_update_docs, install_git_hooks
│       ├── dev_tools.py     # dev tools
│       ├── system_tools.py  # system/health tools
│       ├── analysis_tools.py# structural_search, scan_changes, etc.
│       ├── investigation_tools.py # bug_correlation, hotspots, etc.
│       ├── lifecycle_tools.py# background tasks, verification
│       └── meta_tools.py    # index status, health reports
├── core/                # Pure business logic (NO MCP imports)
│   ├── di_container.py  # ServiceCollection (15+ services)
│   ├── error_handler.py # error_boundary + ToolError
│   ├── rate_limiter.py  # SlidingWindowRateLimiter + CircuitBreaker
│   ├── runtime_coordinator.py # ExecutionVerdict + can_execute()
│   ├── graph.py         # PropertyGraph (SQLite WAL) — nodes/edges
│   ├── doc_sync_engine.py # Auto-sync docs with code (rename hook)
│   ├── search/
│   │   ├── engine.py    # Hybrid search (BM25 + Dense + FTS5 + RRF)
│   │   ├── fts5_mixin.py# FTS5 full-text search
│   │   ├── graph_adapter.py # PropertyGraph → SymbolIndex
│   │   ├── cypher_engine.py # Cypher→SQL
│   │   └── scoring.py   # RRF + MMR diversity
│   ├── indexing/
│   │   ├── indexer.py   # LanceDB vector storage
│   │   ├── db_manager.py# LanceDB lifecycle (PID-lock)
│   │   ├── parser.py    # Tree-sitter AST (16 languages)
│   │   ├── file_guard.py# .gitignore + extension filter
│   │   ├── symbol_index.py # Call Graph (BFS, PageRank)
│   │   └── watchdog.py  # File change watcher
│   └── intelligence/
│       ├── layer.py     # 13 intel_* tools
│       ├── project_context.py # Project state snapshot
│       ├── health.py    # System health checks
│       └── tools_reg.py # Intel tool registration
├── providers/
│   ├── embedder/
│   │   └── remote_embedder.py # ONNX E5-small + LM Studio/Ollama
│   └── reranker/
│       ├── llama_runner.py   # llama-server.exe lifecycle
│       ├── multi_provider.py # Multi-provider reranking
│       └── search_result_reranker.py # Result reranking
└── utils/
    ├── i18n.py          # Internationalization
    ├── paths.py         # SafePathManager
    └── zed_config.py    # Zed settings management
```

**Key principles:**
1. All tools are separate classes with Constructor Injection (via `MCPTool`)
2. Every tool is decorated with `@error_boundary` (JSON + timeout)
3. Single DI container — `create_service_collection()` in `di_container.py`
4. Core layer has ZERO MCP imports

---

## 3. Code Style

- **Formatter**: Black (line length 88)
- **Import order**: isort
- **Type hints**: required for all public APIs
- **Logging**: `logging.getLogger(__name__)` — never `print()` in production code
- **Async**: use `async/await` for I/O; heavy disk ops → `asyncio.to_thread()`

```powershell
# Check formatting
black --check src/
isort --check-only src/

# Auto-format
black src/
isort src/
```

---

## 4. Running Tests

The project has **565+ tests** in `tests/`.

```powershell
# Full suite
pytest tests/ -v

# Fast tests only (no slow/integration/benchmark)
pytest tests/ -v -m "not slow and not integration and not benchmark"

# By marker
pytest tests/ -v -m slow
pytest tests/ -v -m integration
pytest tests/ -v -m benchmark

# By module
pytest tests/test_engine.py -v
pytest tests/test_parser.py -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing
```

**Markers** (defined in `pyproject.toml`):
- `slow` — slow tests
- `integration` — integration tests (require LanceDB)
- `benchmark` — performance benchmarks
- `asyncio` — async tests

### Test categories

| Category | Count | Description |
|----------|-------|-------------|
| Unit | 550+ | No external services, <5s each |
| Integration | 3 | Require LanceDB, marked `@pytest.mark.integration` |
| Benchmark | 6 | Latency/throughput measurement |

### CI pipeline

```bash
# Minimal (every commit)
pytest tests/ -m "not integration and not benchmark" --tb=short -q

# Full (nightly)
pytest tests/ --tb=long -v
```

---

## 5. Adding New MCP Tools

Tools are registered in `src/mcp/server_tools.py` via `register_all_tools()`.
Each tool is a class in `src/mcp/tools/*.py` inheriting from `MCPTool`.

### Tool categories (42 total):

| Category | Count | Key tools |
|----------|-------|-----------|
| **Search** | 3 | `search_code`, `get_symbol_info`, `impact_analysis` |
| **Codebase** | 1 | `codebase(action=rename/move/delete/...)` |
| **Write** | 1 | `write(action=rename/move/delete/replace/insert)` |
| **Analysis** | 5 | `structural_search`, `get_repo_map`, `scan_changes`, etc. |
| **Graph** | 3 | `graph_query`, `cross_repo_search`, `cross_project_deps` |
| **Git** | 1 | `git(action=log/history/branch)` |
| **Indexing** | 1 | `get_index_status`, `notify_change`, `watcher_status` |
| **Docs** | 1 | `generate_docs`, `bump_version`, `auto_update_docs`, `install_git_hooks` |
| **Investigation** | 3 | `get_bug_correlation`, `get_hotspots`, `find_similar_bugs` |
| **Lifecycle** | 3 | `submit_background_task`, `get_task_status`, `verify_action` |
| **System** | 1 | `read_live_file`, `get_health_report`, `get_logs` |
| **Meta** | 1 | index status, health reports |
| **Intelligence** | 13 | `intel_get_runtime_status`, `intel_trigger_reindex`, etc. |
| **Dev** | 3 | `generate_docs`, `bump_version`, `install_git_hooks` |
| **Diagnostic inline** | 7 | `debug_runtime_passport`, `get_runtime_counters`, etc. |
| **Optional** | 1 | `execute_script(code)` (E2B sandbox) |

### Steps to add a new tool:

1. **Create a class** in `src/mcp/tools/<category>.py`:

```python
from src.core.di_container import ServiceCollection
from src.mcp.tools.base import MCPTool
from src.core.error_handler import error_boundary


class MyNewTool(MCPTool):
    """Description for AI agent.

    USE THIS TOOL WHEN:
    - Use case 1
    - Use case 2

    Args:
        param: Description of parameter
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="my_new_tool")

    @error_boundary("my_new_tool", timeout_ms=15000)
    async def execute(self, param: str, **kwargs) -> dict:
        # Implementation
        return {"status": "ok", "result": param}
```

2. **Register** in `src/mcp/server_tools.py`:

```python
from src.mcp.tools.my_module import MyNewTool

def register_all_tools(mcp, services):
    tool_classes = [
        ...
        MyNewTool,
    ]
    for cls in tool_classes:
        tool = cls(services)
        mcp.tool()(tool.execute)
```

3. **Add tests** in `tests/test_<module>.py`.

4. **Update documentation**:
   - `README.md` — Tools section
   - `ARCHITECTURE.md` — if architecture changes
   - `CHANGELOG.md` — add entry

5. **Run verification**:

```powershell
python -m pytest tests/ -q --tb=short
auto_update_docs(action="verify")
```

---

## 6. Adding New Core Modules

Core modules live in `src/core/`. No MCP imports allowed.

### Steps:

1. **Create file** in appropriate `src/core/` subdirectory:

```python
"""Module for ..."""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MyModule:
    def __init__(self, ...):
        ...

    def do_something(self) -> Any:
        """What the method does."""
        ...
```

2. **Register in DI** in `src/core/di_container.py`:

```python
services.add_singleton(MyModule, MyModule(...))
```

3. **Add tests** in `tests/test_my_module.py`.

4. **Update ARCHITECTURE.md**.

5. **Run DocSync** to verify docs match:

```python
from src.core.doc_sync_engine import DocSyncEngine
engine = DocSyncEngine(project_root)
report = engine.sync_all()
```

---

## 7. Commit Messages

Conventional Commits: `type(scope): description`

**Types:** `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`

**Scopes:** `search`, `indexer`, `parser`, `mcp`, `core`, `tests`, `docs`, `doc_sync`

**Examples:**
```
feat(search): add FTS5 full-text search to hybrid pipeline
fix(indexer): handle LanceDB Not found during reindex
docs: update ARCHITECTURE.md with DocSync engine
refactor(doc_sync): clean up suggestion logic
```

---

## 8. PR Process

### Checklist:

- [ ] Branch created from `development` (not `main`)
- [ ] `pytest tests/ -v` — all tests pass
- [ ] `black --check src/` — formatting OK
- [ ] Type hints on all public functions
- [ ] No `print()` in production code (use `logging`)
- [ ] New tools/modules have tests
- [ ] `CHANGELOG.md` updated
- [ ] `README.md` updated (if public API changed)
- [ ] `ARCHITECTURE.md` updated (if architecture changed)
- [ ] DocSync check: `auto_update_docs(action="verify")`

### PR description must include:

1. **What changed** — specific files and functions
2. **Why** — what problem it solves
3. **How tested** — what tests were added/run
4. **Breaking changes** — if any, explicitly noted

---

## 9. Versioning

SemVer: MAJOR.MINOR.PATCH

- **MAJOR** — incompatible API changes
- **MINOR** — new tools/features (backward compatible)
- **PATCH** — bug fixes

Current version in `pyproject.toml`: `3.3.9`

---

## 10. Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'src'` | Run from project root |
| Tests fail with embedding errors | Normal for fallback mode; run with LM Studio for full testing |
| MCP server timeout on first call | Reranker cold start — 2nd call works |
| DocSync reports false positives | Run `auto_update_docs(action="verify")` for current state |

---

*Last updated: 2026-07-21 | DocSync Edition*
