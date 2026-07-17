"""
Юнит-тесты для token-aware поиска символов (search_symbols).

Проверяют, что:
- Запрос `embed_batch` ранжирует `embed_batch` выше `embed_batch_async`
- Prefix-совпадения (query="batch" → name="batch_process") ранжируются выше
  простых ALL_TOKENS (query="batch" → name="embed_batch")
- Пустой/односимвольный запрос не падает
- Обратная совместимость с существующими вызовами
"""

from src.core.symbol_index import SymbolIndex


def _prep_index() -> SymbolIndex:
    """Создаёт SymbolIndex с тестовыми символами.

    Определения:
    - embed_batch (method)
    - embed_batch_async (method)
    - embed (method)
    - batch_process (function)
    - pre_embed_filter (function)

    References:
    - process_file → embed_batch
    - process_file_async → embed_batch_async
    - run_query → embed
    - run_batch → batch_process
    - apply_filter → pre_embed_filter
    """
    idx = SymbolIndex()
    idx.add_definitions("remote_embedder.py", [
        {"name": "embed_batch", "line": 10, "kind": "method"},
    ])
    idx.add_definitions("remote_embedder.py", [
        {"name": "embed_batch_async", "line": 50, "kind": "method"},
    ])
    idx.add_definitions("remote_embedder.py", [
        {"name": "embed", "line": 90, "kind": "method"},
    ])
    idx.add_definitions("mixed.py", [
        {"name": "batch_process", "line": 5, "kind": "function"},
    ])
    idx.add_definitions("filter.py", [
        {"name": "pre_embed_filter", "line": 1, "kind": "function"},
    ])

    idx.add_references("pipeline.py", [
        {"caller": "process_file", "callee": "embed_batch", "line": 100, "file": "pipeline.py"},
    ])
    idx.add_references("pipeline_async.py", [
        {"caller": "process_file_async", "callee": "embed_batch_async", "line": 200, "file": "pipeline_async.py"},
    ])
    idx.add_references("query.py", [
        {"caller": "run_query", "callee": "embed", "line": 15, "file": "query.py"},
    ])
    idx.add_references("batch_utils.py", [
        {"caller": "run_batch", "callee": "batch_process", "line": 30, "file": "batch_utils.py"},
    ])
    idx.add_references("filter_utils.py", [
        {"caller": "apply_filter", "callee": "pre_embed_filter", "line": 10, "file": "filter_utils.py"},
    ])
    return idx


class TestSearchSymbolsTokenAware:
    """Token-aware scoring для search_symbols."""

    def test_exact_match_first(self):
        """Точное совпадение — всегда первое."""
        idx = _prep_index()
        results = idx.search_symbols("embed_batch")
        names = [r.symbol for r in results]
        assert names[0] == "embed_batch", f"Expected exact match first, got {names[0]}"

    def test_embed_batch_before_embed_batch_async(self):
        """Запрос embed_batch → embed_batch выше рангом чем embed_batch_async."""
        idx = _prep_index()
        results = idx.search_symbols("embed_batch")
        names = [r.symbol for r in results]
        eb_pos = names.index("embed_batch")
        eba_pos = names.index("embed_batch_async")
        assert eb_pos < eba_pos, (
            f"embed_batch[pos={eb_pos}] should be before "
            f"embed_batch_async[pos={eba_pos}]"
        )

    def test_prefix_match_beats_all_tokens(self):
        """prefix (batch→batch_process) выше рангом чем all_tokens (batch→embed_batch)."""
        idx = _prep_index()
        results = idx.search_symbols("batch")
        names = [r.symbol for r in results]
        assert names[0] == "batch_process", f"Expected batch_process (prefix) first, got {names[0]}"
        bp_pos = names.index("batch_process")
        eb_pos = names.index("embed_batch")
        assert bp_pos < eb_pos, (
            f"batch_process[pos={bp_pos}] should be before "
            f"embed_batch[pos={eb_pos}]"
        )

    def test_embed_prefix_over_embed_token(self):
        """prefix (embed→embed_batch) выше рангом чем partial (embed→pre_embed_filter)."""
        idx = _prep_index()
        results = idx.search_symbols("embed")
        names = [r.symbol for r in results]
        assert names[0] == "embed", "Exact match 'embed' should be first"
        eb_pos = names.index("embed_batch")
        pre_pos = names.index("pre_embed_filter")
        assert eb_pos < pre_pos, (
            f"embed_batch[pos={eb_pos}] (prefix) should be before "
            f"pre_embed_filter[pos={pre_pos}] (all_tokens)"
        )

    def test_all_tokens_match_for_compound_query(self):
        """compound query 'batch_async' → embed_batch_async на первом месте."""
        idx = _prep_index()
        results = idx.search_symbols("batch_async")
        names = [r.symbol for r in results]
        assert names[0] == "embed_batch_async", (
            f"Expected 'embed_batch_async' first, got {names[0]}"
        )

    def test_empty_query_does_not_crash(self):
        """Пустой запрос не должен вызывать ошибок."""
        idx = _prep_index()
        results = idx.search_symbols("")
        assert len(results) > 0, "Empty query should return symbols"

    def test_single_char_query_does_not_crash(self):
        """Односимвольный запрос не должен вызывать ошибок."""
        idx = _prep_index()
        results = idx.search_symbols("e")
        assert len(results) > 0, "Single char query should return symbols"

    def test_no_match_returns_empty(self):
        """Полностью несовпадающий запрос — пустой результат."""
        idx = _prep_index()
        results = idx.search_symbols("zzz_nonexistent_999")
        assert len(results) == 0, "No symbols should match random query"

    def test_batch_async_finds_embed_batch_async(self):
        """Подстрока 'batch_async' находит embed_batch_async (substring + all_tokens)."""
        idx = _prep_index()
        results = idx.search_symbols("batch_async")
        names = [r.symbol for r in results]
        assert "embed_batch_async" in names, (
            f"embed_batch_async should be found for 'batch_async', got {names}"
        )
        assert names[0] == "embed_batch_async"
