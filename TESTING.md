# Testing

## Test Suite

| File | Tests | What It Covers |
|------|-------|----------------|
| `tests/test_agentic_search.py` | 25 | Query decomposition, subquery relations, deduplication, result limits |
| `tests/test_reranker.py` | 20 | Multi-Provider Reranker (Ollama/LM Studio), fallback, JSON parsing |
| `tests/test_cross_repo_search.py` | 21 | @-mention parsing, ProjectRegistry, RRF merge, cross-repo output |
| `tests/test_deep_search.py` | 15 | Iterative search with query refinement |
| `tests/test_embedder.py` | 6 | LM Studio / Ollama embedder |
| `tests/test_indexer_project_path.py` | 6 | Path normalization and DB path generation |
| `tests/test_integration.py` | — | End-to-end MCP server + indexer + searcher |
| `tests/test_mutation_core.py` | 3 | Core mutation/change detection |
| `tests/test_multi_project_query_expansion.py` | 25 | Query expansion across projects |
| `tests/test_parser.py` | 4 | Tree-sitter AST parsing |
| `tests/test_searcher.py` | 4 | Hybrid search (BM25 + Dense + RRF) |
| `test_connection.py` | 1 | Smoke test: FileGuard + MCP server init |
| `test_automation.py` | 1 | Automated test runner |
| **Total** | **131** | |

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

### `tests/test_reranker.py`

All 20 tests should pass. Key assertions:

- `test_rerank_via_lm_studio_sorts_by_score` — LM Studio response correctly sorts chunks by score
- `test_rerank_via_ollama_sorts_by_score` — Ollama response correctly sorts chunks
- `test_ollama_priority_over_lm_studio` — Ollama preferred when both available
- `test_fallback_when_no_providers_available` — returns original order when both down
- `test_fallback_on_connection_error` / `test_fallback_on_timeout` — graceful degradation
- `test_malformed_json_fallback_to_regex` — regex parser handles dirty JSON
- `test_parse_scores_json_*` — 5 parsing variants (pure, markdown, surrounded, empty, gibberish)

### `tests/test_cross_repo_search.py`

All 21 tests should pass. Key assertions:

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

## Reranker Testing

The `MultiProviderReranker` tests use `unittest.mock.AsyncMock` to simulate LM Studio and Ollama responses — no actual servers required.

```powershell
# Run only reranker tests
pytest tests/test_reranker.py -v

# Run with coverage for reranker module
pytest tests/test_reranker.py --cov=src.core.reranker --cov-report=term-missing
```

### Test Categories

| Category | Tests | Description |
|----------|-------|-------------|
| Provider success | 4 | LM Studio, Ollama sorting + priority + top_n |
| Fallback | 4 | No providers, ConnectError, Timeout, broken JSON |
| Edge cases | 3 | Empty list, single chunk, text truncation |
| Initialization | 2 | Provider detection, both down |
| Parsing | 5 | Pure JSON, markdown, regex, empty, gibberish |
| Prompt building | 1 | Query and indices in prompt |

## CI Requirements

- Python 3.10+
- All tests in `tests/` must pass before merge
- `test_connection.py` requires the project source tree on disk (not CI-friendly)
- No external services required for unit tests (all mocked)

---

*Last updated: 2026-06-28*
