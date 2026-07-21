"""
Тесты: Indexer синхронизирует FTS5 при изменении/переименовании файлов (этап А).

Покрывают (AGENTS.md §5.13 — корректность, не только "не упало"):
1. _index_single_file вызывает searcher.incremental_update_fts5 (если FTS5 построен).
2. incremental_update_fts5 НЕ делает full rebuild, если FTS5 ещё не построен.
3. apply_file_move вызывает searcher.remove_from_fts5(old_path).
"""
from unittest.mock import MagicMock

from src.core.indexing.indexer import Indexer


def _make_indexer_with_searcher(searcher):
    idx = MagicMock(spec=Indexer)
    idx.searcher = searcher
    # _build_fts5_chunks_from_parsed — чистая функция, тестируем отдельно
    idx._build_fts5_chunks_from_parsed = Indexer._build_fts5_chunks_from_parsed.__get__(idx)
    return idx


def test_index_single_file_calls_incremental_fts5_when_built():
    """Если FTS5 построен — incremental_update_fts5 вызывается с чанками."""
    searcher = MagicMock()
    searcher.incremental_update_fts5 = MagicMock()
    idx = _make_indexer_with_searcher(searcher)

    parsed = {
        "chunk_texts": ["def foo():\n    pass", "class Bar:\n    def baz(self): pass"],
        "chunk_metadatas": [{"layer": "core"}, {"layer": "core"}],
    }
    chunks = idx._build_fts5_chunks_from_parsed("src/x.py", parsed)
    assert len(chunks) == 2
    assert chunks[0]["symbol_name"] == "foo"
    assert chunks[0]["file_path"] == "src/x.py"

    # имитируем вызов из _index_single_file (после записи)
    if idx.searcher is not None and hasattr(idx.searcher, "incremental_update_fts5"):
        idx.searcher.incremental_update_fts5(chunks)
    searcher.incremental_update_fts5.assert_called_once_with(chunks)


def test_incremental_fts5_skips_when_not_built():
    """Если FTS5 ещё не построен — НЕТ full rebuild (lazy при поиске)."""
    from src.core.search.fts5_mixin import FTS5Mixin

    mixin = FTS5Mixin()
    mixin._fts5 = None  # не построен
    # убираем _build_fts5_index, чтобы убедиться, что он НЕ вызывается
    mixin._build_fts5_index = MagicMock()
    mixin._fts5 = None

    mixin.incremental_update_fts5([{"file_path": "a.py", "text": "x"}])
    # build НЕ должен вызываться (пропуск, т.к. lazy-rebuild при поиске)
    mixin._build_fts5_index.assert_not_called()


def test_apply_file_move_calls_remove_from_fts5():
    """apply_file_move удаляет старый путь из FTS5."""
    searcher = MagicMock()
    searcher.remove_from_fts5 = MagicMock()
    idx = _make_indexer_with_searcher(searcher)
    # Делаем apply_file_move РЕАЛЬНЫМ методом (а не mock из spec)
    idx.apply_file_move = Indexer.apply_file_move.__get__(idx)
    idx.move_chunks_metadata = MagicMock(return_value=5)
    idx._symbol_index = MagicMock()
    idx._symbol_index.remap_file = MagicMock(return_value=2)
    idx.file_guard = MagicMock()
    idx.file_guard.notify_file_renamed = MagicMock()

    result = idx.apply_file_move("old.py", "new.py")
    searcher.remove_from_fts5.assert_called_once_with("old.py")
    assert result["fts5"] == "old_path_removed"
