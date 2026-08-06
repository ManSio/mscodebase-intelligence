"""
Tests for next_step hints in MCP tools (Axon pattern, audit.md п.5).

Проверяет, что ключевые инструменты ведут агента к следующему действию:
  - search_code: строка с 💡 next_step
  - get_symbol_info: строка с 💡 next_step (ok + not-found)
  - impact_analysis: dict с ключом next_step (ok + warning)
  - graph_query: dict с ключом next_step для всех query_type
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp.tools.graph_tools import GraphQueryTool
from src.mcp.tools.search_tools import (
    GetSymbolInfoTool,
    ImpactAnalysisTool,
    SearchCodeTool,
)


@pytest.fixture
def services():
    return MagicMock()


# ═══════════════════════════════════════════════════════════════
# search_code
# ═══════════════════════════════════════════════════════════════

class TestSearchCodeNextStep:
    async def test_ok_path_has_next_step(self, services):
        tool = SearchCodeTool(services)
        tool.require_ready_project = AsyncMock()
        mock_searcher = MagicMock()
        mock_searcher.search_with_mode.return_value = {
            "results": [
                {"text": "def f(): pass", "metadata": {"file": "a.py", "chunk_index": 0}}
            ],
            "timing_ms": {},
        }
        with (
            patch.object(SearchCodeTool, "resolve_searcher", return_value=mock_searcher),
            patch.object(SearchCodeTool, "_project_header", return_value=""),
        ):
            out = await tool.execute(query="def f", mode="fast")

        assert "next_step" in out
        assert "get_symbol_info" in out, f"ok-path должен предлагать get_symbol_info:\n{out}"

    async def test_empty_results_has_guidance(self, services):
        tool = SearchCodeTool(services)
        tool.require_ready_project = AsyncMock()
        mock_searcher = MagicMock()
        mock_searcher.search_with_mode.return_value = {
            "results": [],
            "timing_ms": {},
        }
        with (
            patch.object(SearchCodeTool, "resolve_searcher", return_value=mock_searcher),
            patch.object(SearchCodeTool, "_project_header", return_value=""),
            patch("src.mcp.tools.search_tools._grep_fallback", return_value=None),
        ):
            out = await tool.execute(query="__no_such_symbol_xyz__", mode="fast")

        assert "next_step" in out
        assert "graph_query" in out, f"empty-path должен предлагать graph_query:\n{out}"


# ═══════════════════════════════════════════════════════════════
# get_symbol_info
# ═══════════════════════════════════════════════════════════════

class TestGetSymbolInfoNextStep:
    async def test_main_path_has_next_step(self, services):
        tool = GetSymbolInfoTool(services)
        tool.require_ready_project = AsyncMock()
        mock_si = MagicMock()
        mock_si.build_call_graph.return_value = {
            "definition": [{"file": "a.py", "line": 3}],
            "callers": [],
            "callees": [],
        }
        with patch.object(GetSymbolInfoTool, "resolve_symbol_index", return_value=mock_si):
            out = await tool.execute(query="SomeClass")

        assert "next_step" in out
        assert "impact_analysis" in out

    async def test_not_found_has_next_step(self, services):
        tool = GetSymbolInfoTool(services)
        tool.require_ready_project = AsyncMock()
        mock_si = MagicMock()
        mock_si.build_call_graph.return_value = {"definition": [], "callers": [], "callees": []}
        mock_si.search_symbols.return_value = []
        with patch.object(GetSymbolInfoTool, "resolve_symbol_index", return_value=mock_si):
            out = await tool.execute(query="GhostSymbol")

        assert "next_step" in out
        assert "search_code" in out


# ═══════════════════════════════════════════════════════════════
# impact_analysis
# ═══════════════════════════════════════════════════════════════

class TestImpactAnalysisNextStep:
    async def test_ok_path_has_next_step_key(self, services):
        tool = ImpactAnalysisTool(services)
        tool.require_ready_project = AsyncMock()
        mock_si = MagicMock()
        mock_si.get_impact_analysis.return_value = {
            "call_graph": {"definition": [{"file": "a.py"}]},
            "direct_callers": 1,
            "transitive_callers": 2,
            "direct_callees": 3,
            "transitive_callees": 4,
            "risk_level": "high",
            "risk_score": 0.8,
            "affected_files": ["a.py"],
            "affected_modules": ["src.a"],
        }
        with patch.object(ImpactAnalysisTool, "resolve_symbol_index", return_value=mock_si):
            res = await tool.execute(symbol="f", depth=2)

        # error_boundary рендерит dict в markdown-строку; next_step виден как bullet
        assert isinstance(res, str)
        assert "next step" in res, f"ok-path должен содержать next step:\n{res}"
        assert "read_live_file" in res

    async def test_warning_path_has_next_step_key(self, services):
        tool = ImpactAnalysisTool(services)
        tool.require_ready_project = AsyncMock()
        mock_si = MagicMock()
        mock_si.get_impact_analysis.return_value = {
            "call_graph": {"definition": []},
            "direct_callers": 0,
        }
        with patch.object(ImpactAnalysisTool, "resolve_symbol_index", return_value=mock_si):
            res = await tool.execute(symbol="ghost", depth=2)

        assert isinstance(res, str)
        assert "next step" in res, f"warning-path должен содержать next step:\n{res}"
        assert "search_code" in res


# ═══════════════════════════════════════════════════════════════
# graph_query (все query_type)
# ═══════════════════════════════════════════════════════════════

class TestGraphQueryNextStep:
    async def test_all_query_types_have_next_step(self, services):
        mock_indexer = MagicMock()
        mock_indexer.project_path = "D:/project"
        mock_si = MagicMock()

        payloads = {
            "impact": {"risk_score": 0.5, "direct_impact": [], "tests_to_run": []},
            "feature": {"files": [], "symbols": []},
            "deps": {"depends_on": [], "depended_by": []},
            "tests": ["tests/test_a.py"],
        }

        with (
            patch("src.core.graph_rag.GraphRAGQueryEngine") as mock_engine_cls,
            patch.object(GraphQueryTool, "resolve_indexer", return_value=mock_indexer),
            patch.object(GraphQueryTool, "resolve_symbol_index", return_value=mock_si),
        ):
            mock_engine_cls.return_value.query_impact.return_value = payloads["impact"]
            mock_engine_cls.return_value.query_feature.return_value = payloads["feature"]
            mock_engine_cls.return_value.query_dependencies.return_value = payloads["deps"]
            mock_engine_cls.return_value.query_tests.return_value = payloads["tests"]

            tool = GraphQueryTool(services)
            for qtype in payloads:
                res = await tool.execute(action="query", query_type=qtype, target="x")
                # error_boundary рендерит dict в markdown-строку
                assert isinstance(res, str), f"{qtype}: {res}"
                assert "next step" in res, f"{qtype} должен содержать next step:\n{res}"
