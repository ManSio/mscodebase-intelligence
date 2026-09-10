"""Tests for get_symbol_info AMBIGUOUS path (issue #21 read-path fork).

When build_call_graph returns >1 definition, get_symbol_info MUST NOT silently
pick defs[0]. It must surface all candidates and label the result AMBIGUOUS.

Single-definition (len == 1) should keep the existing "📄 Definition:" behavior.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp.tools.search_tools import GetSymbolInfoTool


@pytest.fixture
def services():
    return MagicMock()


class TestGetSymbolInfoAmbiguous:
    """AMBIGUOUS path: len(defs) > 1 → all candidates shown, no silent pick."""

    async def test_ambiguous_returns_status_and_all_candidates(self, services):
        tool = GetSymbolInfoTool(services)
        tool.require_ready_project = AsyncMock()
        mock_si = MagicMock()
        mock_si.build_call_graph.return_value = {
            "definition": [
                {"file": "src/auth/login.py", "line": 12, "kind": "function_definition"},
                {"file": "src/utils/helpers.py", "line": 88, "kind": "function_definition"},
            ],
            "callers": [],
            "callees": [],
        }
        with patch.object(GetSymbolInfoTool, "resolve_symbol_index", return_value=mock_si):
            out = await tool.execute(query="validate_token")

        assert "AMBIGUOUS" in out, f"must surface AMBIGUOUS status:\n{out}"
        assert "src/auth/login.py" in out, "first candidate must appear"
        assert "src/utils/helpers.py" in out, "second candidate must appear"
        assert "2 definitions" in out or "defs, 2" in out, "count must be shown"

    async def test_ambiguous_does_not_pick_single_definition(self, services):
        tool = GetSymbolInfoTool(services)
        tool.require_ready_project = AsyncMock()
        mock_si = MagicMock()
        mock_si.build_call_graph.return_value = {
            "definition": [
                {"file": "src/a.py", "line": 1, "kind": "func"},
                {"file": "src/b.py", "line": 2, "kind": "func"},
                {"file": "src/c.py", "line": 3, "kind": "func"},
            ],
            "callers": [{"symbol": "caller", "file": "src/caller.py", "line": 5, "kind": "call"}],
            "callees": [],
        }
        with patch.object(GetSymbolInfoTool, "resolve_symbol_index", return_value=mock_si):
            out = await tool.execute(query="run")

        assert "AMBIGUOUS" in out
        # Must NOT contain the single-definition "📄 Definition:" header
        assert "📄 Definition:" not in out, (
            "must not silently pick one definition when ambiguous"
        )
        # All 3 candidates must appear
        assert "src/a.py" in out
        assert "src/b.py" in out
        assert "src/c.py" in out

    async def test_single_definition_keeps_existing_behavior(self, services):
        tool = GetSymbolInfoTool(services)
        tool.require_ready_project = AsyncMock()
        mock_si = MagicMock()
        mock_si.build_call_graph.return_value = {
            "definition": [
                {"file": "src/core/engine.py", "line": 42, "kind": "function_definition"},
            ],
            "callers": [],
            "callees": [],
        }
        with patch.object(GetSymbolInfoTool, "resolve_symbol_index", return_value=mock_si):
            out = await tool.execute(query="search")

        assert "AMBIGUOUS" not in out, "single def must not trigger AMBIGUOUS"
        assert "📄 Definition: `src/core/engine.py` line 42" in out
