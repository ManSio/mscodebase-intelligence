# Testing

## Test Suite

| File | Tests | What It Covers |
|------|-------|----------------|
| `tests/test_agentic_search.py` | 12 | Query decomposition, subquery relations, deduplication, result limits |
| `tests/test_cross_repo_search.py` | 14 | @-mention parsing, ProjectRegistry, RRF merge, cross-repo output |
| `tests/test_deep_search.py` | — | Iterative search with query refinement |
| `tests/test_embedder.py` | — | LM Studio / Ollama / ONNX embedder |
| `tests/test_indexer_project_path.py` | — | Path normalization and DB path generation |
| `tests/test_integration.py` | — | End-to-end MCP server + indexer + searcher |
| `tests/test_mutation_core.py` | — | Core mutation/change detection |
| `tests/test_parser.py` | — | Tree-sitter AST parsing |
| `tests/test_searcher.py` | — | Hybrid search (BM25 + Dense + RRF) |
| `test_connection.py` | 1 | Smoke test: FileGuard + MCP server init |
| `test_automation.py` | — | Automated test runner |

## Running Tests

```powershell
# Run full suite
pytest tests/ -v

# Run a single test module
pytest tests/test_agentic_search.py -v
pytest tests/test_cross_repo_search.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing

# Run the smoke test (requires project on disk)
python test_connection.py
```

## Expected Results

### `tests/test_agentic_search.py`

All 12 tests should pass. Key assertions:

- `test_simple_query_unchanged` — single-word query stays as 1 subquery
- `test_split_by_and` — `"авторизация и проверка прав"` → 2 subqueries
- `test_split_by_question_words` — `"как работает ... и где ..."` → ≥2 subqueries
- `test_max_subqueries_limit` — never more than 4 subqueries
- `test_deduplication_across_subqueries` — same file:chunk not duplicated
- `test_max_total_results_limit` — results capped at `max_total_results`

### `tests/test_cross_repo_search.py`

All 14 tests should pass. Key assertions:

- `test_no_mentions` — plain query returns unchanged, empty project list
- `test_single_mention` — `"auth @backend"` → query=`"auth"`, projects=`["backend"]`
- `test_find_by_prefix` — prefix `"backend"` matches `"backend-api"` and `"backend-worker"`
- `test_merge_results_rrf` — results from multiple projects merged correctly
- `test_merge_deduplication` — same filename in different projects kept as separate results

### `test_connection.py`

Expected output:

```
🔍 Проверка проекта: D:\Project\MSCodeBase
✅ FileGuard: src/main.py прошел проверку
⏳ Инициализация компонентов...
✅ Компоненты созданы успешно!
```

## CI Requirements

- Python 3.10+
- All tests in `tests/` must pass before merge
- `test_connection.py` requires the project source tree on disk (not CI-friendly)

---

*Last updated: 2026-06-28*
