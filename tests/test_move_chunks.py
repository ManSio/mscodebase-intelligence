"""
Tests for P0 LanceDB meta-patching (move_chunks_metadata + apply_file_move).

Covers:
1. move_chunks_metadata: updates file_path in LanceDB WITHOUT re-embedding
2. apply_file_move: coordinates LanceDB + BM25 + SymbolIndex
3. _infer_module_name / _infer_layer: metadata recalculation
4. Edge cases: empty table, same path, non-existent file, Windows paths
"""

from __future__ import annotations

from types import MethodType
from unittest.mock import MagicMock

import pandas as pd
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_indexer():
    """Creates a mock Indexer for apply_file_move delegation tests.

    Attributes:
        move_chunks_metadata: mocked to return 5
        _symbol_index: real SymbolIndex instance
        searcher: MagicMock with _reset_bm25
        file_guard: MagicMock
        table: MagicMock
    """
    from src.core.indexer import Indexer
    from src.core.symbol_index import SymbolIndex

    indexer = MagicMock(spec=Indexer)

    # Real SymbolIndex for remap testing
    indexer._symbol_index = SymbolIndex()

    # Cache state
    indexer._cached_total_chunks = 10
    indexer._cached_unique_files = {"old/file.py"}

    # Sub-component mocks
    indexer.searcher = MagicMock()
    indexer.file_guard = MagicMock()
    indexer.table = MagicMock()

    # Stub the high-level API so delegation tests can verify the call
    indexer.move_chunks_metadata = MagicMock(return_value=5)

    return indexer


@pytest.fixture
def indexer_for_test():
    """Indexer mock with real _infer_module_name / _infer_layer bound.

    This fixture is used when we want to call the *real*
    move_chunks_metadata implementation while mocking the LanceDB table.
    """
    from src.core.indexer import Indexer

    indexer = MagicMock(spec=Indexer)
    indexer.table = MagicMock()
    indexer._cached_total_chunks = 10
    indexer._cached_unique_files = {"old/file.py"}

    # Bind the real helper methods so that move_chunks_metadata
    # recalculates metadata correctly.
    indexer._infer_module_name = MethodType(Indexer._infer_module_name, indexer)
    indexer._infer_layer = MethodType(Indexer._infer_layer, indexer)

    return indexer


@pytest.fixture
def symbol_index():
    """SymbolIndex seeded with test data for remap_file verification."""
    from src.core.symbol_index import SymbolIndex

    si = SymbolIndex()
    si.add_definitions("old/file.py", [
        {"name": "old_func", "line": 1, "kind": "function"},
        {"name": "OldClass", "line": 10, "kind": "class"},
    ])
    si.add_references("main.py", [
        {"caller": "main", "callee": "old_func", "line": 5, "file": "main.py"},
    ])
    return si


# ── Tests: move_chunks_metadata ───────────────────────────────────────────


class TestMoveChunksMetadata:
    """Tests for Indexer.move_chunks_metadata()."""

    def test_returns_zero_for_nonexistent_path(self, indexer_for_test):
        """move_chunks_metadata returns 0 if old path not in table."""
        from src.core.indexer import Indexer

        # Empty DataFrame → no chunks found
        indexer_for_test.table.search.return_value \
            .where.return_value \
            .limit.return_value \
            .to_pandas.return_value = pd.DataFrame()

        result = Indexer.move_chunks_metadata(
            indexer_for_test, "old/file.py", "new/file.py",
        )
        assert result == 0

        # Should NOT attempt to delete or re-insert
        indexer_for_test.table.delete.assert_not_called()
        indexer_for_test.table.add.assert_not_called()

    def test_updates_file_path_in_lancedb(self, indexer_for_test):
        """After move, chunks are found under new path, not old."""
        from src.core.indexer import Indexer

        df = pd.DataFrame({
            "file_path": ["old/file.py", "old/file.py"],
            "text": ["chunk1", "chunk2"],
            "module_name": ["file", "file"],
            "layer": ["root", "root"],
            "indexed_at": ["2024-01-01", "2024-01-01"],
        })
        indexer_for_test.table.search.return_value \
            .where.return_value \
            .limit.return_value \
            .to_pandas.return_value = df

        result = Indexer.move_chunks_metadata(
            indexer_for_test, "old/file.py", "new/file.py",
        )
        assert result == 2

        # Old entries deleted
        indexer_for_test.table.delete.assert_called_once_with(
            "file_path = 'old/file.py'",
        )

        # Re-inserted records have new file_path
        args, _ = indexer_for_test.table.add.call_args
        records = args[0]
        assert len(records) == 2
        for record in records:
            assert record["file_path"] == "new/file.py"

    def test_updates_module_name(self, indexer_for_test):
        """module_name is recalculated from new path via _infer_module_name."""
        from src.core.indexer import Indexer

        df = pd.DataFrame({
            "file_path": ["old/file.py"],
            "text": ["chunk"],
            "module_name": ["old"],
            "layer": ["root"],
            "indexed_at": ["2024-01-01"],
        })
        indexer_for_test.table.search.return_value \
            .where.return_value \
            .limit.return_value \
            .to_pandas.return_value = df

        Indexer.move_chunks_metadata(
            indexer_for_test, "old/file.py", "src/core/foo.py",
        )

        args, _ = indexer_for_test.table.add.call_args
        records = args[0]
        assert records[0]["module_name"] == "core.foo"

    def test_updates_layer(self, indexer_for_test):
        """layer metadata is recalculated from new path via _infer_layer."""
        from src.core.indexer import Indexer

        df = pd.DataFrame({
            "file_path": ["old/file.py"],
            "text": ["chunk"],
            "module_name": ["old"],
            "layer": ["root"],
            "indexed_at": ["2024-01-01"],
        })
        indexer_for_test.table.search.return_value \
            .where.return_value \
            .limit.return_value \
            .to_pandas.return_value = df

        Indexer.move_chunks_metadata(
            indexer_for_test, "old/file.py", "src/core/foo.py",
        )

        args, _ = indexer_for_test.table.add.call_args
        records = args[0]
        assert records[0]["layer"] == "core"

    def test_invalidates_cache(self, indexer_for_test):
        """_cached_total_chunks set to None and old path removed after move."""
        from src.core.indexer import Indexer

        df = pd.DataFrame({
            "file_path": ["old/file.py"],
            "text": ["chunk"],
            "module_name": ["old"],
            "layer": ["root"],
            "indexed_at": ["2024-01-01"],
        })
        indexer_for_test.table.search.return_value \
            .where.return_value \
            .limit.return_value \
            .to_pandas.return_value = df

        Indexer.move_chunks_metadata(
            indexer_for_test, "old/file.py", "new/file.py",
        )

        assert indexer_for_test._cached_total_chunks is None
        assert "old/file.py" not in indexer_for_test._cached_unique_files

    def test_handles_same_path(self, indexer_for_test):
        """Same old and new path → returns 0 (no-op)."""
        from src.core.indexer import Indexer

        result = Indexer.move_chunks_metadata(
            indexer_for_test, "file.py", "file.py",
        )
        assert result == 0

        # No database interaction should occur
        indexer_for_test.table.delete.assert_not_called()
        indexer_for_test.table.add.assert_not_called()

    def test_handles_windows_backslashes(self, indexer_for_test):
        """Backslashes normalized to forward slashes before SQL filter."""
        from src.core.indexer import Indexer

        df = pd.DataFrame({
            "file_path": ["old/file.py"],
            "text": ["chunk"],
            "module_name": ["old"],
            "layer": ["root"],
            "indexed_at": ["2024-01-01"],
        })
        indexer_for_test.table.search.return_value \
            .where.return_value \
            .limit.return_value \
            .to_pandas.return_value = df

        Indexer.move_chunks_metadata(
            indexer_for_test, "old\\file.py", "new\\file.py",
        )

        # WHERE clause must use forward slashes
        where_call = indexer_for_test.table.search.return_value.where
        where_call.assert_called_once()
        where_arg = where_call.call_args[0][0]
        assert "old/file.py" in where_arg
        assert "old\\file.py" not in where_arg

        # DELETE must also use forward slashes
        delete_call = indexer_for_test.table.delete
        delete_call.assert_called_once()
        delete_arg = delete_call.call_args[0][0]
        assert "old/file.py" in delete_arg
        assert "old\\file.py" not in delete_arg

    def test_handles_single_quotes_in_path(self, indexer_for_test):
        """Single quotes in path are properly escaped for SQL safety."""
        from src.core.indexer import Indexer

        df = pd.DataFrame({
            "file_path": ["john's/file.py"],
            "text": ["chunk"],
            "module_name": ["file"],
            "layer": ["root"],
            "indexed_at": ["2024-01-01"],
        })
        indexer_for_test.table.search.return_value \
            .where.return_value \
            .limit.return_value \
            .to_pandas.return_value = df

        Indexer.move_chunks_metadata(
            indexer_for_test, "john's/file.py", "new/file.py",
        )

        # WHERE clause should double the single quote
        where_call = indexer_for_test.table.search.return_value.where
        where_call.assert_called_once()
        where_arg = where_call.call_args[0][0]
        assert "john''s" in where_arg
        assert "john's" not in where_arg

        # DELETE clause also escaped
        delete_call = indexer_for_test.table.delete
        delete_call.assert_called_once()
        delete_arg = delete_call.call_args[0][0]
        assert "john''s" in delete_arg


# ── Tests: apply_file_move ────────────────────────────────────────────────


class TestApplyFileMove:
    """Tests for Indexer.apply_file_move()."""

    def test_calls_move_chunks_metadata(self, mock_indexer):
        """apply_file_move delegates to move_chunks_metadata."""
        from src.core.indexer import Indexer

        result = Indexer.apply_file_move(mock_indexer, "old.py", "new.py")

        mock_indexer.move_chunks_metadata.assert_called_once_with(
            "old.py", "new.py",
        )
        assert result["status"] == "ok"
        assert result["chunks_moved"] == 5

    def test_calls_symbol_index_remap(self, mock_indexer):
        """apply_file_move calls SymbolIndex.remap_file and moves defs."""
        from src.core.indexer import Indexer

        # Seed a definition so we can observe the remap
        si = mock_indexer._symbol_index
        si.add_definitions("old.py", [
            {"name": "old_func", "line": 1, "kind": "function"},
        ])

        Indexer.apply_file_move(mock_indexer, "old.py", "new.py")

        # The definition should now point to the new file
        defs = si.find_definitions("old_func")
        assert len(defs) > 0
        for d in defs:
            assert d.file_path.endswith("/new.py")

    def test_invalidates_bm25(self, mock_indexer):
        """apply_file_move resets BM25 cache via searcher._reset_bm25."""
        from src.core.indexer import Indexer

        Indexer.apply_file_move(mock_indexer, "old.py", "new.py")

        mock_indexer.searcher._reset_bm25.assert_called_once()

    def test_returns_chunk_count(self, mock_indexer):
        """Result dict includes chunks_moved and symbol_updates."""
        from src.core.indexer import Indexer

        result = Indexer.apply_file_move(mock_indexer, "old.py", "new.py")

        assert result["chunks_moved"] == 5
        assert result["symbol_updates"] == 0  # empty SymbolIndex → 0
        assert result["bm25"] == "invalidated"

    def test_handles_missing_searcher(self, mock_indexer):
        """apply_file_move works gracefully when searcher is None."""
        mock_indexer.searcher = None
        from src.core.indexer import Indexer

        result = Indexer.apply_file_move(mock_indexer, "old.py", "new.py")

        assert result["status"] == "ok"
        assert result["chunks_moved"] == 5

    def test_handles_missing_file_guard_notify(self, mock_indexer):
        """apply_file_move works when file_guard lacks notify_file_renamed."""
        # Remove the method so hasattr returns False
        del mock_indexer.file_guard.notify_file_renamed
        from src.core.indexer import Indexer

        result = Indexer.apply_file_move(mock_indexer, "old.py", "new.py")

        assert result["status"] == "ok"
        assert result["chunks_moved"] == 5


# ── Tests: _infer_module_name / _infer_layer ──────────────────────────────


class TestInferMetadata:
    """Tests for _infer_module_name and _infer_layer (no self access needed)."""

    def test_module_name_src_core(self):
        """src/core/foo.py → 'core.foo'"""
        from src.core.indexer import Indexer

        name = Indexer._infer_module_name(None, "src/core/foo.py")
        assert name == "core.foo"

    def test_module_name_mcp_tools(self):
        """src/mcp/tools/bar.py → 'mcp.tools.bar'"""
        from src.core.indexer import Indexer

        name = Indexer._infer_module_name(None, "src/mcp/tools/bar.py")
        assert name == "mcp.tools.bar"

    def test_module_name_root_level(self):
        """README.md → 'README' (single component, no package prefix)."""
        from src.core.indexer import Indexer

        name = Indexer._infer_module_name(None, "README.md")
        assert name == "README"

    def test_module_name_app_prefix(self):
        """app/models/user.py → 'models.user' (app is a skip_dir)."""
        from src.core.indexer import Indexer

        name = Indexer._infer_module_name(None, "app/models/user.py")
        assert name == "models.user"

    def test_module_name_lib_prefix(self):
        """lib/utils/helpers.py → 'utils.helpers' """
        from src.core.indexer import Indexer

        name = Indexer._infer_module_name(None, "lib/utils/helpers.py")
        assert name == "utils.helpers"

    def test_module_name_without_skip_dir(self):
        """core/indexer.py → 'indexer' (no skip_dir match → first dir skipped)."""
        from src.core.indexer import Indexer

        name = Indexer._infer_module_name(None, "core/indexer.py")
        assert name == "indexer"

    def test_layer_core(self):
        """src/core/foo.py → 'core'"""
        from src.core.indexer import Indexer

        layer = Indexer._infer_layer(None, "src/core/foo.py")
        assert layer == "core"

    def test_layer_mcp_tools(self):
        """src/mcp/tools/bar.py → 'mcp_tools'"""
        from src.core.indexer import Indexer

        layer = Indexer._infer_layer(None, "src/mcp/tools/bar.py")
        assert layer == "mcp_tools"

    def test_layer_mcp_no_tools(self):
        """src/mcp/handler.py → 'mcp' (tools not in path)."""
        from src.core.indexer import Indexer

        layer = Indexer._infer_layer(None, "src/mcp/handler.py")
        assert layer == "mcp"

    def test_layer_tests(self):
        """tests/test_foo.py → 'tests'"""
        from src.core.indexer import Indexer

        layer = Indexer._infer_layer(None, "tests/test_foo.py")
        assert layer == "tests"

    def test_layer_utils(self):
        """src/utils/helpers.py → 'utils'"""
        from src.core.indexer import Indexer

        layer = Indexer._infer_layer(None, "src/utils/helpers.py")
        assert layer == "utils"

    def test_layer_docs(self):
        """docs/index.md → 'docs'"""
        from src.core.indexer import Indexer

        layer = Indexer._infer_layer(None, "docs/index.md")
        assert layer == "docs"

    def test_layer_root(self):
        """README.md → 'root' (no known layer detected)."""
        from src.core.indexer import Indexer

        layer = Indexer._infer_layer(None, "README.md")
        assert layer == "root"

    def test_layer_windows_backslashes(self):
        """Windows-style paths are normalised before layer detection."""
        from src.core.indexer import Indexer

        layer = Indexer._infer_layer(None, "src\\core\\foo.py")
        assert layer == "core"
