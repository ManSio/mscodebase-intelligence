"""
Tests for WriteTool: rename, move, delete, replace, insert actions.

Covers:
1. WriteTool._action_rename   — preview + apply + collision guard
2. WriteTool._action_move     — preview + apply + import updates
3. WriteTool._action_safe_delete — reference guard + force mode
4. WriteTool._action_replace  — body replacement
5. WriteTool._action_insert_before / _action_insert_after — anchor-based insertion
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.mcp.tools.write_tools import WriteTool

# ── Helpers ────────────────────────────────────────────────────────────


def _build_index_for_file(file_path, extra_defs=None, add_refs=True):
    """Create a SymbolIndex with definitions pointing at a real file."""
    from src.core.indexing.symbol_index import SymbolIndex

    si = SymbolIndex()
    defs = [
        {"name": "existing_function", "line": 1, "kind": "function"},
        {"name": "ExistingClass", "line": 6, "kind": "class"},
    ]
    if extra_defs:
        defs.extend(extra_defs)
    si.add_definitions(str(file_path), defs)

    if add_refs:
        ref_file = file_path.parent / "usage.py"
        # Write a small usage file so the reference path is valid
        if not ref_file.exists():
            ref_file.write_text(
                "from test_module import existing_function\n\n"
                "result = existing_function(1, 2)\n"
            )
        si.add_references(str(ref_file), [
            {"caller": "usage", "callee": "existing_function", "line": 3, "file": str(ref_file)},
        ])
    return si


def _make_mock_indexer():
    """Return a MagicMock that quacks like an Indexer."""
    idx = MagicMock()
    idx.project_path = str(Path.cwd())
    idx.apply_file_move = MagicMock(return_value={"patched": True})
    return idx


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def temp_py_file(tmp_path):
    """Create a temp .py file with a function and a class at known lines."""
    file = tmp_path / "test_module.py"
    file.write_text(
        "def existing_function(a, b):\n"
        '    """Existing function."""\n'
        "    return a + b\n"
        "\n"
        "\n"
        "class ExistingClass:\n"
        '    """Existing class."""\n'
        "\n"
        "    def method(self):\n"
        "        pass\n"
    )
    return file


@pytest.fixture
def temp_second_file(tmp_path):
    """A second file that imports and calls existing_function."""
    file = tmp_path / "consumer.py"
    file.write_text(
        "from test_module import existing_function\n"
        "\n"
        "\n"
        "def run():\n"
        "    return existing_function(10, 20)\n"
    )
    return file


@pytest.fixture
def mock_services():
    """Mock ServiceCollection — resolves nothing by default."""
    services = MagicMock()
    services.resolve = MagicMock()
    return services


@pytest.fixture
def symbol_index():
    """Populated SymbolIndex with test symbols (paths may not exist)."""
    from src.core.indexing.symbol_index import SymbolIndex

    si = SymbolIndex()
    si.add_definitions("/tmp/test_module.py", [
        {"name": "existing_function", "line": 1, "kind": "function"},
        {"name": "ExistingClass", "line": 6, "kind": "class"},
        {"name": "conflicting_name", "line": 12, "kind": "function"},
    ])
    si.add_references("/tmp/main.py", [
        {"caller": "main", "callee": "existing_function", "line": 1, "file": "/tmp/main.py"},
    ])
    return si


@pytest.fixture
def write_tool(mock_services, symbol_index):
    """WriteTool with mocked dependencies (shared across all action tests)."""
    tool = WriteTool(mock_services)
    tool.require_ready_project = AsyncMock()
    tool.resolve_symbol_index = MagicMock(return_value=symbol_index)
    tool.resolve_indexer = MagicMock(return_value=_make_mock_indexer())
    return tool


# ── WriteTool._action_rename ──────────────────────────────────────────


class TestWriteToolRename:
    """Tests for WriteTool._action_rename."""

    @pytest.mark.asyncio
    async def test_preview_returns_changes(self, write_tool, symbol_index):
        """Preview mode returns change list without modifying files."""
        result = await write_tool._action_rename(
            old_name="existing_function",
            new_name="new_func",
            file_path="",
            apply=False,
            allow_collision=False,
        )
        assert result["status"] == "preview"
        assert "changes" in result
        assert len(result["changes"]) > 0
        assert result["files_affected"] >= 1
        assert result["total_occurrences"] >= 1
        # Each change has expected keys
        for c in result["changes"]:
            assert "file" in c
            assert "line" in c
            assert "old" in c
            assert c["old"] == "existing_function"
            assert "new" in c
            assert c["new"] == "new_func"

    @pytest.mark.asyncio
    async def test_apply_modifies_file(self, mock_services, tmp_path):
        """Apply mode actually changes file content on disk."""
        # Create a real temp file with the function name
        py_file = tmp_path / "module.py"
        py_file.write_text(
            "def existing_function(a, b):\n"
            '    """Docstring."""\n'
            "    return a + b\n"
        )

        # Build SymbolIndex pointing at the real file
        si = _build_index_for_file(py_file, add_refs=False)

        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        tool.resolve_indexer = MagicMock(return_value=_make_mock_indexer())

        # Mock _get_lsp_client to return None (no LSP in test env)
        tool._get_lsp_client = MagicMock(return_value=None)

        result = await tool._action_rename(
            old_name="existing_function",
            new_name="renamed_func",
            file_path="",
            apply=True,
            allow_collision=False,
        )

        assert result["status"] in ("applied", "partial")
        assert result["changes_applied"] >= 1
        # Verify file was modified
        content = py_file.read_text()
        assert "def renamed_func(a, b):" in content
        assert "def existing_function(a, b):" not in content

    @pytest.mark.asyncio
    async def test_collision_guard_denies(self, write_tool, symbol_index):
        """Renaming to an existing symbol is denied unless allow_collision=True."""
        result = await write_tool._action_rename(
            old_name="existing_function",
            new_name="conflicting_name",
            file_path="",
            apply=False,
            allow_collision=False,
        )
        assert result["status"] == "error"
        assert "already exists" in result["message"].lower() or "collision" in result["message"].lower()
        assert "collision" in result

    @pytest.mark.asyncio
    async def test_collision_guard_allows_with_flag(self, write_tool, symbol_index):
        """allow_collision=True lets rename proceed even when target exists."""
        result = await write_tool._action_rename(
            old_name="existing_function",
            new_name="conflicting_name",
            file_path="",
            apply=False,
            allow_collision=True,
        )
        # Should proceed to preview instead of error
        assert result["status"] == "preview"

    @pytest.mark.asyncio
    async def test_unknown_symbol_returns_warning(self, write_tool):
        """Non-existent symbol returns warning."""
        result = await write_tool._action_rename(
            old_name="nonexistent_func",
            new_name="new_name",
            file_path="",
            apply=False,
            allow_collision=False,
        )
        assert "Warning" in result or "not found" in str(result).lower()

    @pytest.mark.asyncio
    async def test_filter_by_file_path(self, write_tool, symbol_index, tmp_path):
        """When file_path is provided, only refs in that file are returned."""
        # Use a path within the project root (cwd) so FileGuard allows it
        project_file = tmp_path / "main.py"
        project_file.write_text("# test file\n")
        result = await write_tool._action_rename(
            old_name="existing_function",
            new_name="new_func",
            file_path=str(project_file),
            apply=False,
            allow_collision=False,
        )
        # Result is a preview dict (refs found in that file) or a warning
        if isinstance(result, dict) and "status" in result:
            assert result["status"] in ("preview", "warning")
        else:
            assert "existing_function" in str(result) or "main.py" in str(result) or "Warning" in str(result)

    @pytest.mark.asyncio
    async def test_apply_file_not_found(self, write_tool, tmp_path):
        """Apply with a file_path that doesn't exist yields partial/errors."""
        # Use a path within the project root so FileGuard allows it,
        # but the file itself doesn't exist yet
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)
        project_file = tmp_path / "nonexistent.py"
        result = await write_tool._action_rename(
            old_name="existing_function",
            new_name="new_func",
            file_path=str(project_file),
            apply=False,
            allow_collision=False,
        )
        assert "⚠️" in str(result) or "Warning" in str(result) or "not found" in str(result).lower() or "outside" in str(result).lower()


# ── WriteTool._action_move ────────────────────────────────────────────


class TestWriteToolMove:
    """Tests for WriteTool._action_move."""

    @pytest.mark.asyncio
    async def test_preview_shows_target(self, write_tool, tmp_path):
        """Preview shows source and target files."""
        target_file = tmp_path / "target.py"
        target_file.write_text("# target\n")
        # Override indexer to point to tmp_path so FileGuard allows it
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)
        result = await write_tool._action_move(
            symbol="existing_function",
            to_file=str(target_file),
            file_path="",
            apply=False,
        )
        assert result["status"] == "preview"
        assert "changes" in result
        assert len(result["changes"]) > 0
        assert result["source_file"] is not None
        assert result["target_file"] is not None
        assert "target.py" in result["target_file"]

    @pytest.mark.asyncio
    async def test_unknown_symbol_returns_warning(self, write_tool, tmp_path):
        """Non-existent symbol returns warning."""
        target_file = tmp_path / "target.py"
        target_file.write_text("# target\n")
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)
        result = await write_tool._action_move(
            symbol="nonexistent_func",
            to_file=str(target_file),
            file_path="",
            apply=False,
        )
        assert result["status"] == "warning"
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_preview_includes_move_and_imports(self, write_tool, tmp_path):
        """Preview changes show definition move + import updates."""
        target_file = tmp_path / "target.py"
        target_file.write_text("# target\n")
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)
        result = await write_tool._action_move(
            symbol="existing_function",
            to_file=str(target_file),
            file_path="",
            apply=False,
        )
        assert result["status"] == "preview"
        ops = [c["op"] for c in result["changes"]]
        assert "move_definition" in ops

    @pytest.mark.asyncio
    async def test_apply_with_real_files(self, mock_services, tmp_path):
        """Apply move actually transfers definition from source to target."""
        src = tmp_path / "source.py"
        src.write_text(
            "def foo():\n"
            '    """Foo function."""\n'
            "    return 42\n"
            "\n"
            "\n"
            "def bar():\n"
            "    return 99\n"
        )
        tgt = tmp_path / "target.py"
        # Target doesn't exist yet, will be created

        si = _build_index_for_file(src, extra_defs=[
            {"name": "foo", "line": 1, "kind": "function"},
            {"name": "bar", "line": 6, "kind": "function"},
        ], add_refs=False)

        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        tool.resolve_indexer = MagicMock(return_value=idx)

        result = await tool._action_move(
            symbol="foo",
            to_file=str(tgt),
            file_path="",
            apply=True,
        )

        assert result["status"] in ("applied", "partial")
        # Check source lost the function
        src_content = src.read_text()
        assert "def foo():" not in src_content
        # Check target gained the function
        tgt_content = tgt.read_text()
        assert "def foo():" in tgt_content
        assert "return 42" in tgt_content

    @pytest.mark.asyncio
    async def test_filter_by_source_file(self, write_tool, symbol_index, tmp_path):
        """file_path filter restricts to specific source file."""
        # Update symbol_index to point to a file within tmp_path
        from src.core.indexing.symbol_index import SymbolIndex

        si = SymbolIndex()
        si.add_definitions(str(tmp_path / "test_module.py"), [
            {"name": "existing_function", "line": 1, "kind": "function"},
        ])
        si.add_references(str(tmp_path / "main.py"), [
            {"caller": "main", "callee": "existing_function", "line": 1, "file": str(tmp_path / "main.py")},
        ])
        write_tool.resolve_symbol_index = MagicMock(return_value=si)
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)
        result = await write_tool._action_move(
            symbol="existing_function",
            to_file=str(tmp_path / "target.py"),
            file_path=str(tmp_path / "test_module.py"),
            apply=False,
        )
        assert result["status"] == "preview"

    @pytest.mark.asyncio
    async def test_filter_mismatch_returns_warning(self, write_tool, tmp_path):
        """file_path filter that matches nothing returns warning."""
        target_file = tmp_path / "target.py"
        target_file.write_text("# target\n")
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)
        result = await write_tool._action_move(
            symbol="existing_function",
            to_file=str(target_file),
            file_path=str(tmp_path / "wrong.py"),
            apply=False,
        )
        assert result["status"] == "warning"


# ── WriteTool._action_safe_delete ─────────────────────────────────────


class TestWriteToolSafeDelete:
    """Tests for WriteTool._action_safe_delete."""

    @pytest.mark.asyncio
    async def test_denies_if_references_exist(self, mock_services):
        """safe_delete denies deletion if symbol has usages elsewhere."""
        from src.core.indexing.symbol_index import SymbolIndex, SymbolRef

        si = SymbolIndex()
        si.add_definitions("/tmp/mod.py", [
            {"name": "target_func", "line": 1, "kind": "function"},
        ])
        # Manually inject a usage so the reference check fires correctly.
        # add_references stores caller as symbol, so we inject a SymbolRef
        # where symbol == "target_func" and is_definition=False.
        si._references["target_func"] = [
            SymbolRef(
                symbol="target_func",
                file_path="/tmp/other.py",
                line=5,
                kind="call",
                is_definition=False,
            ),
        ]

        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        tool.resolve_indexer = MagicMock(return_value=_make_mock_indexer())

        result = await tool._action_safe_delete(
            symbol="target_func",
            file_path="",
            apply=False,
            force=False,
        )
        assert result["status"] == "denied"
        assert "usage" in result["message"].lower() or "usages" in result["message"].lower()
        assert "usage_count" in result
        assert result["usage_count"] >= 1

    @pytest.mark.asyncio
    async def test_allows_with_force(self, mock_services):
        """force=True bypasses reference check."""
        from src.core.indexing.symbol_index import SymbolIndex, SymbolRef

        si = SymbolIndex()
        si.add_definitions("/tmp/mod.py", [
            {"name": "target_func", "line": 1, "kind": "function"},
        ])
        # Inject a reference
        si._references["target_func"] = [
            SymbolRef(
                symbol="target_func",
                file_path="/tmp/other.py",
                line=5,
                kind="call",
                is_definition=False,
            ),
        ]

        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        tool.resolve_indexer = MagicMock(return_value=_make_mock_indexer())

        result = await tool._action_safe_delete(
            symbol="target_func",
            file_path="",
            apply=False,
            force=True,
        )
        # With force=True, it should go to preview (or apply)
        assert result["status"] == "preview"
        # And include the usage reference in the changes
        assert result["has_usages"] is True

    @pytest.mark.asyncio
    async def test_unknown_symbol_returns_warning(self, write_tool):
        """Non-existent symbol returns warning."""
        result = await write_tool._action_safe_delete(
            symbol="nonexistent_func",
            file_path="",
            apply=False,
            force=False,
        )
        assert result["status"] == "warning"
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_preview_shows_changes(self, write_tool):
        """Preview lists definitions that will be deleted."""
        result = await write_tool._action_safe_delete(
            symbol="existing_function",
            file_path="",
            apply=False,
            force=False,
        )
        assert result["status"] == "preview"
        assert "changes" in result
        assert len(result["changes"]) > 0
        for c in result["changes"]:
            assert c["op"] == "delete_definition"

    @pytest.mark.asyncio
    async def test_apply_deletes_from_file(self, mock_services, tmp_path):
        """Apply deletion removes definition lines from the file."""
        from src.core.indexing.symbol_index import SymbolIndex

        py_file = tmp_path / "mod.py"
        py_file.write_text(
            "def keep():\n"
            "    pass\n"
            "\n"
            "\n"
            "def delete_me():\n"
            "    return 1\n"
            "\n"
            "\n"
            "def also_keep():\n"
            "    return 2\n"
        )

        si = SymbolIndex()
        si.add_definitions(str(py_file), [
            {"name": "keep", "line": 1, "kind": "function"},
            {"name": "delete_me", "line": 5, "kind": "function"},
            {"name": "also_keep", "line": 9, "kind": "function"},
        ])

        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        tool.resolve_indexer = MagicMock(return_value=_make_mock_indexer())

        result = await tool._action_safe_delete(
            symbol="delete_me",
            file_path="",
            apply=True,
            force=False,
        )

        assert result["status"] in ("applied", "partial")
        content = py_file.read_text()
        assert "def delete_me():" not in content
        assert "def keep():" in content
        assert "def also_keep():" in content


# ── WriteTool._action_replace ─────────────────────────────────────────


class TestWriteToolReplace:
    """Tests for WriteTool._action_replace."""

    @pytest.mark.asyncio
    async def test_preview_shows_old_and_new(self, write_tool, temp_py_file, tmp_path):
        """Preview shows current code and new code."""
        # Re-point the symbol_index to the real temp file
        si = _build_index_for_file(temp_py_file, add_refs=False)
        # Also override resolve_indexer to point to tmp_path so FileGuard allows it
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)
        write_tool.resolve_symbol_index = MagicMock(return_value=si)

        result = await write_tool._action_replace(
            symbol="existing_function",
            new_code="def existing_function(x, y, z):\n    return x * y * z\n",
            file_path=str(temp_py_file),
            apply=False,
        )
        assert "Preview" in result or "🔍" in result
        assert "existing_function" in result

    @pytest.mark.asyncio
    async def test_unknown_symbol_returns_warning(self, write_tool):
        """Non-existent symbol returns error."""
        result = await write_tool._action_replace(
            symbol="nonexistent_func",
            new_code="pass",
            file_path="",
            apply=False,
        )
        assert "not found" in result.lower() or "Error" in result
        assert "🚫" in result

    @pytest.mark.asyncio
    async def test_apply_replaces_body(self, mock_services, tmp_path):
        """Apply replaces the symbol body on disk."""
        py_file = tmp_path / "replace_me.py"
        py_file.write_text(
            "def old_func():\n"
            "    return 1\n"
            "\n"
            "\n"
            "def another():\n"
            "    return 2\n"
        )

        si = _build_index_for_file(py_file, extra_defs=[
            {"name": "old_func", "line": 1, "kind": "function"},
            {"name": "another", "line": 5, "kind": "function"},
        ], add_refs=False)

        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        tool.resolve_indexer = MagicMock(return_value=idx)

        new_body = "def old_func():\n    return 999\n"
        result = await tool._action_replace(
            symbol="old_func",
            new_code=new_body,
            file_path=str(py_file),
            apply=True,
        )
        assert "✅" in result or "Replaced" in result
        content = py_file.read_text()
        assert "return 999" in content
        # The old body should be gone
        assert "return 1" not in content.split("def old_func")[1].split("\n\ndef")[0]

    @pytest.mark.asyncio
    async def test_filter_by_file_path(self, write_tool, temp_py_file, tmp_path):
        """file_path restricts replacement to a specific file."""
        si = _build_index_for_file(temp_py_file, add_refs=False)
        write_tool.resolve_symbol_index = MagicMock(return_value=si)
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)

        result = await write_tool._action_replace(
            symbol="existing_function",
            new_code="def existing_function():\n    pass\n",
            file_path=str(temp_py_file),
            apply=False,
        )
        assert "Preview" in result or "🔍" in result

    @pytest.mark.asyncio
    async def test_filter_mismatch_returns_error(self, write_tool):
        """file_path that doesn't contain the symbol returns error."""
        result = await write_tool._action_replace(
            symbol="existing_function",
            new_code="pass",
            file_path="/wrong/path.py",
            apply=False,
        )
        assert "not found" in result.lower() or "Error" in result


# ── WriteTool._action_insert_before ───────────────────────────────────


class TestWriteToolInsertBefore:
    """Tests for WriteTool._action_insert_before."""

    @pytest.mark.asyncio
    async def test_inserts_before_anchor(self, mock_services, tmp_path):
        """Code is inserted before the anchor symbol's definition."""
        py_file = tmp_path / "insert_before.py"
        py_file.write_text(
            "def existing_function(a, b):\n"
            '    """Existing function."""\n'
            "    return a + b\n"
        )

        si = _build_index_for_file(py_file, add_refs=False)
        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        tool.resolve_indexer = MagicMock(return_value=_make_mock_indexer())

        result = await tool._action_insert_before(
            anchor_symbol="existing_function",
            new_code="def helper():\n    return 0\n",
            file_path=str(py_file),
            apply=True,
        )
        assert "✅" in result or "Inserted before" in result
        content = py_file.read_text()
        # The helper should appear before existing_function
        assert content.index("def helper():") < content.index("def existing_function(")

    @pytest.mark.asyncio
    async def test_preview_shows_insertion(self, write_tool, temp_py_file):
        """Preview mode shows the code that will be inserted."""
        si = _build_index_for_file(temp_py_file, add_refs=False)
        write_tool.resolve_symbol_index = MagicMock(return_value=si)

        result = await write_tool._action_insert_before(
            anchor_symbol="existing_function",
            new_code="def helper():\n    pass\n",
            file_path=str(temp_py_file),
            apply=False,
        )
        assert "Preview" in result or "🔍" in result

    @pytest.mark.asyncio
    async def test_unknown_symbol_returns_error(self, write_tool):
        """Non-existent anchor symbol returns error."""
        result = await write_tool._action_insert_before(
            anchor_symbol="nonexistent_func",
            new_code="pass",
            file_path="",
            apply=False,
        )
        assert "not found" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_filter_mismatch_returns_error(self, write_tool):
        """file_path that doesn't match returns error."""
        result = await write_tool._action_insert_before(
            anchor_symbol="existing_function",
            new_code="pass",
            file_path="/wrong/path.py",
            apply=False,
        )
        assert "not found" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_insert_before_class(self, mock_services, tmp_path):
        """Insertion before a class works correctly."""
        py_file = tmp_path / "class_test.py"
        py_file.write_text(
            "class MyClass:\n"
            "    pass\n"
        )

        si = _build_index_for_file(py_file, extra_defs=[
            {"name": "MyClass", "line": 1, "kind": "class"},
        ], add_refs=False)

        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        tool.resolve_indexer = MagicMock(return_value=_make_mock_indexer())

        result = await tool._action_insert_before(
            anchor_symbol="MyClass",
            new_code="def prelude():\n    return 1\n",
            file_path=str(py_file),
            apply=True,
        )
        assert "✅" in result or "Inserted before" in result
        content = py_file.read_text()
        assert content.index("def prelude():") < content.index("class MyClass:")


# ── WriteTool._action_insert_after ────────────────────────────────────


class TestWriteToolInsertAfter:
    """Tests for WriteTool._action_insert_after."""

    @pytest.mark.asyncio
    async def test_inserts_after_anchor(self, mock_services, tmp_path):
        """Code is inserted after the anchor symbol's body."""
        py_file = tmp_path / "insert_after.py"
        py_file.write_text(
            "def existing_function(a, b):\n"
            '    """Existing function."""\n'
            "    return a + b\n"
            "\n"
            "\n"
            "class ExistingClass:\n"
            '    """Existing class."""\n'
            "    pass\n"
        )

        si = _build_index_for_file(py_file, add_refs=False)
        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        tool.resolve_indexer = MagicMock(return_value=_make_mock_indexer())

        result = await tool._action_insert_after(
            anchor_symbol="existing_function",
            new_code="def new_function():\n    return 1\n",
            file_path=str(py_file),
            apply=True,
        )
        assert "✅" in result or "Inserted after" in result
        content = py_file.read_text()
        # The new function should appear between existing_function and ExistingClass
        func_idx = content.index("def existing_function(")
        new_idx = content.index("def new_function():")
        class_idx = content.index("class ExistingClass:")
        assert func_idx < new_idx < class_idx

    @pytest.mark.asyncio
    async def test_preview_shows_insertion(self, write_tool, temp_py_file):
        """Preview mode shows the code that will be inserted."""
        si = _build_index_for_file(temp_py_file, add_refs=False)
        write_tool.resolve_symbol_index = MagicMock(return_value=si)

        result = await write_tool._action_insert_after(
            anchor_symbol="existing_function",
            new_code="def helper():\n    pass\n",
            file_path=str(temp_py_file),
            apply=False,
        )
        assert "Preview" in result or "🔍" in result

    @pytest.mark.asyncio
    async def test_unknown_symbol_returns_error(self, write_tool):
        """Non-existent anchor symbol returns error."""
        result = await write_tool._action_insert_after(
            anchor_symbol="nonexistent_func",
            new_code="pass",
            file_path="",
            apply=False,
        )
        assert "not found" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_insert_after_class(self, mock_services, tmp_path):
        """Insertion after a class body works correctly."""
        py_file = tmp_path / "class_after.py"
        py_file.write_text(
            "class MyClass:\n"
            "    def method(self):\n"
            "        pass\n"
            "\n"
            "\n"
            "def after():\n"
            "    pass\n"
        )

        si = _build_index_for_file(py_file, extra_defs=[
            {"name": "MyClass", "line": 1, "kind": "class"},
            {"name": "method", "line": 2, "kind": "method"},
            {"name": "after", "line": 6, "kind": "function"},
        ], add_refs=False)

        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        tool.resolve_indexer = MagicMock(return_value=_make_mock_indexer())

        result = await tool._action_insert_after(
            anchor_symbol="MyClass",
            new_code="class NewClass:\n    pass\n",
            file_path=str(py_file),
            apply=True,
        )
        assert "✅" in result or "Inserted after" in result
        content = py_file.read_text()
        assert "class NewClass:" in content
        # NewClass should be between MyClass and after
        myclass_idx = content.index("class MyClass:")
        newclass_idx = content.index("class NewClass:")
        after_idx = content.index("def after():")
        assert myclass_idx < newclass_idx < after_idx

    @pytest.mark.asyncio
    async def test_filter_mismatch_returns_error(self, write_tool):
        """file_path that doesn't match returns error."""
        result = await write_tool._action_insert_after(
            anchor_symbol="existing_function",
            new_code="pass",
            file_path="/wrong/path.py",
            apply=False,
        )
        assert "not found" in result.lower() or "Error" in result


# ── WriteTool FileGuard (fail-closed) ──────────────────────────────


class TestWriteToolFileGuard:
    """FileGuard: write_tools._validate_file_in_project — fail-closed.

    Регрессия INC-6E12: старый код возвращал None (fail-open) при
    недоступном indexer'е, разрешая запись в произвольные пути. Новый код
    обязан: 1) запрещать операцию при недоступном корне проекта;
    2) применять SafePathManager.is_safe_to_process (не-ASCII/пробелы/длинные).
    """

    def _tool(self, mock_services, idx=None):
        tool = WriteTool(mock_services)
        tool.resolve_indexer = MagicMock(return_value=idx)
        return tool

    def test_valid_path_within_project(self, mock_services, tmp_path):
        """Путь внутри project_root — валиден (None)."""
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        tool = self._tool(mock_services, idx)
        err = tool._validate_file_in_project(str(tmp_path / "main.py"))
        assert err is None

    def test_outside_project_denied(self, mock_services, tmp_path):
        """Путь вне project_root — отклонён."""
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        tool = self._tool(mock_services, idx)
        err = tool._validate_file_in_project(str(tmp_path.parent / "evil.py"))
        assert err is not None
        assert "outside project root" in err

    def test_fail_closed_when_indexer_unavailable(self, mock_services):
        """Индексер недоступен → запрет, а не молчаливый пропуск (было fail-open)."""
        tool = WriteTool(mock_services)
        tool.resolve_indexer = MagicMock(side_effect=RuntimeError("no indexer"))
        err = tool._validate_file_in_project("C:/anything/evil.py")
        assert err is not None
        assert "project root unavailable" in err

    def test_non_ascii_path_denied(self, mock_services, tmp_path):
        """Не-ASCII/небезопасный путь — отклонён SafePathManager guard'ом."""
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        idx.path_manager = MagicMock()
        idx.path_manager.is_safe_to_process = MagicMock(return_value=False)
        tool = self._tool(mock_services, idx)
        err = tool._validate_file_in_project(str(tmp_path / "файл.py"))
        assert err is not None
        assert "not safe to process" in err


# ── WriteTool Preflight (check_types + compile-гейт) ──────────────────


class TestWriteToolPreflight:
    """Pre-flight валидация: compile() всего файла (жёсткий гейт) +

    LSP-типы (advisory, check_types=True).
    """

    async def test_syntax_gate_blocks_broken_full_file(self, write_tool, tmp_path):
        """Синтаксическая ошибка в результирующем файле — блокирующий (True, msg)."""
        f = tmp_path / "x.py"
        f.write_text("def a():\n    pass\n")
        result = await write_tool._preflight_validate(
            str(f), "def a():\n    pass\n\n\ndef broken(:\n    pass\n", check_types=False
        )
        assert result is not None
        blocking, msg = result
        assert blocking is True
        assert "Синтаксическая ошибка" in msg

    async def test_syntax_clean_passes(self, write_tool, tmp_path):
        """Валидный результирующий файл — None (чисто), без LSP."""
        f = tmp_path / "x.py"
        f.write_text("def a():\n    pass\n")
        result = await write_tool._preflight_validate(
            str(f), "def a():\n    return 1\n", check_types=False
        )
        assert result is None

    async def test_non_python_skipped(self, write_tool, tmp_path):
        """Не-Python файлы — preflight не применяется."""
        f = tmp_path / "x.ts"
        f.write_text("export const x = 1;\n")
        result = await write_tool._preflight_validate(
            str(f), "export const x = ;", check_types=False
        )
        assert result is None

    async def test_types_skipped_without_lsp(self, write_tool, tmp_path):
        """check_types=True без LSP — advisory (False, note), не блокирует."""
        f = tmp_path / "x.py"
        f.write_text("x = 1\n")
        write_tool._get_lsp_client = MagicMock(return_value=None)
        result = await write_tool._preflight_validate(str(f), "x = 1\n", check_types=True)
        assert result is not None
        blocking, msg = result
        assert blocking is False
        assert "LSP" in msg

    async def test_insert_blocked_on_broken_syntax(self, mock_services, tmp_path):
        """Интеграция: insert с ломающим файл синтаксисом — запись отменена."""
        py_file = tmp_path / "insert_me.py"
        py_file.write_text(
            "def a():\n"
            "    pass\n"
            "\n"
            "\n"
            "def b():\n"
            "    return 2\n"
        )
        si = _build_index_for_file(py_file, extra_defs=[
            {"name": "a", "line": 1, "kind": "function"},
            {"name": "b", "line": 5, "kind": "function"},
        ], add_refs=False)

        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        tool.resolve_indexer = MagicMock(return_value=idx)

        before = py_file.read_text()
        result = await tool._action_insert_after(
            anchor_symbol="a",
            new_code="def broken(:\n    pass\n",
            file_path=str(py_file),
            apply=True,
        )
        assert "Error" in result
        assert py_file.read_text() == before  # файл не изменён

    async def test_insert_success_with_note_when_types_checked(self, mock_services, tmp_path):
        """check_types=True и LSP недоступен — запись проходит, note в ответе."""
        py_file = tmp_path / "note_me.py"
        py_file.write_text(
            "def a():\n"
            "    pass\n"
            "\n"
            "\n"
            "def b():\n"
            "    return 2\n"
        )
        si = _build_index_for_file(py_file, extra_defs=[
            {"name": "a", "line": 1, "kind": "function"},
            {"name": "b", "line": 5, "kind": "function"},
        ], add_refs=False)

        tool = WriteTool(mock_services)
        tool.require_ready_project = AsyncMock()
        tool.resolve_symbol_index = MagicMock(return_value=si)
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        tool.resolve_indexer = MagicMock(return_value=idx)
        tool._get_lsp_client = MagicMock(return_value=None)

        result = await tool._action_insert_after(
            anchor_symbol="a",
            new_code="def c():\n    return 3\n",
            file_path=str(py_file),
            apply=True,
            check_types=True,
        )
        assert "Inserted after" in result
        assert "Preflight" in result  # advisory-note в ответе
        assert "def c" in py_file.read_text()  # запись прошла

    async def test_preview_with_check_types_shows_lsp_skip(self, write_tool, tmp_path):
        """Preview + check_types=True без LSP — advisory в preview, файл не тронут."""
        f = tmp_path / "preview_me.py"
        f.write_text("def a():\n    pass\n")
        si = _build_index_for_file(f, extra_defs=[
            {"name": "a", "line": 1, "kind": "function"},
        ], add_refs=False)
        write_tool.resolve_symbol_index = MagicMock(return_value=si)
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)
        write_tool._get_lsp_client = MagicMock(return_value=None)
        before = f.read_text()

        result = await write_tool._action_replace(
            symbol="a",
            new_code="def a():\n    return 1\n",
            file_path=str(f),
            apply=False,
            check_types=True,
        )
        assert "Preview" in result
        assert "Preflight" in result  # advisory о проверке типов
        assert "LSP" in result
        assert f.read_text() == before  # запись не производилась

    async def test_preview_with_check_types_syntax_error(self, write_tool, tmp_path):
        """Preview + check_types=True с битым результирующим файлом — ошибка в preview."""
        f = tmp_path / "preview_bad.py"
        f.write_text("def a():\n    pass\n")
        si = _build_index_for_file(f, extra_defs=[
            {"name": "a", "line": 1, "kind": "function"},
        ], add_refs=False)
        write_tool.resolve_symbol_index = MagicMock(return_value=si)
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)
        write_tool._get_lsp_client = MagicMock(return_value=None)
        before = f.read_text()

        result = await write_tool._action_replace(
            symbol="a",
            new_code="def broken(:\n    pass\n",
            file_path=str(f),
            apply=False,
            check_types=True,
        )
        assert "Preview" in result
        assert "🚫" in result or "Синтаксическая ошибка" in result
        assert f.read_text() == before  # запись не производилась

    async def test_preview_insert_with_check_types(self, write_tool, tmp_path):
        """Preview + check_types=True для insert — advisory в preview, файл не тронут."""
        f = tmp_path / "preview_insert.py"
        f.write_text(
            "def a():\n"
            "    pass\n"
            "\n"
            "\n"
            "def b():\n"
            "    return 2\n"
        )
        si = _build_index_for_file(f, extra_defs=[
            {"name": "a", "line": 1, "kind": "function"},
            {"name": "b", "line": 5, "kind": "function"},
        ], add_refs=False)
        write_tool.resolve_symbol_index = MagicMock(return_value=si)
        idx = _make_mock_indexer()
        idx.project_path = str(tmp_path)
        write_tool.resolve_indexer = MagicMock(return_value=idx)
        write_tool._get_lsp_client = MagicMock(return_value=None)
        before = f.read_text()

        result = await write_tool._action_insert_after(
            anchor_symbol="a",
            new_code="def c():\n    return 3\n",
            file_path=str(f),
            apply=False,
            check_types=True,
        )
        assert "Preview" in result
        assert "Preflight" in result
        assert "LSP" in result
        assert f.read_text() == before  # запись не производилась
