# Contributing

## Setup

```powershell
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd MSCodeBase
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Code Style

- **Formatter**: Black (line length 88)
- **Import order**: isort
- **Type hints**: required for public APIs
- **Logging**: `logging.getLogger(__name__)` — never `print()` in production code

```powershell
# Check formatting
black --check src/
isort --check-only src/

# Auto-format
black src/
isort src/
```

## Running Tests

```powershell
# Full suite
pytest tests/ -v

# Single module
pytest tests/test_searcher.py -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing

# Smoke test (requires project on disk)
python test_connection.py
```

All tests must pass before creating a PR.

## Commit Messages

Format: `type(scope): description`

- `feat(searcher): add BM25 hybrid search implementation`
- `fix(indexer): handle empty embeddings from LM Studio`
- `docs: update README with architecture diagram`
- `test(cross-repo): add @-mention parsing tests`

## Pull Request Process

1. Create branch from `development`
2. Make changes following code standards above
3. Run `pytest tests/ -v` and `black --check src/`
4. Create PR with description of what changed and why
5. Address review feedback

## Adding New MCP Tools

1. Implement the tool function in `src/mcp/server.py` inside `create_mcp_server()`
2. Register it with `@mcp.tool()`
3. Add unit tests in `tests/`
4. Update `README.md` tool table and `ARCHITECTURE.md` tools section
5. Add entry to `CHANGELOG.md`

## Adding New Core Modules

1. Create module in `src/core/`
2. Import and wire it in `src/mcp/server.py` or `src/core/indexer.py`
3. Add tests in `tests/test_<module_name>.py`
4. Update architecture diagram in `ARCHITECTURE.md`

## Versioning

We use SemVer: MAJOR (breaking), MINOR (new features), PATCH (bug fixes).

---

*Last updated: 2026-06-28*
