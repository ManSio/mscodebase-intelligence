"""
Тесты для GraphRAG Query Engine.
"""

import tempfile
from pathlib import Path

import pytest

from src.core.graph_rag import GraphRAGQueryEngine


class TestGraphRAGQueryEngine:
    """Тесты GraphRAGQueryEngine."""

    def test_init(self, tmp_path):
        """Инициализация движка."""
        engine = GraphRAGQueryEngine(tmp_path)
        assert engine.project_path == tmp_path
        assert engine._graph == {}

    def test_build_graph_empty(self, tmp_path):
        """Построение графа без symbol_index."""
        engine = GraphRAGQueryEngine(tmp_path)
        graph = engine.build_graph()

        assert "nodes" in graph
        assert "stats" in graph
        assert graph["stats"]["total_nodes"] == 0

    def test_query_impact_no_symbol_index(self, tmp_path):
        """Impact запрос без symbol_index."""
        engine = GraphRAGQueryEngine(tmp_path)
        result = engine.query_impact("test_symbol")

        assert result["symbol"] == "test_symbol"
        assert result["direct_impact"] == []

    def test_query_feature(self, tmp_path):
        """Feature запрос."""
        engine = GraphRAGQueryEngine(tmp_path)
        result = engine.query_feature("test_feature")

        assert result["feature"] == "test_feature"
        assert "files" in result
        assert "symbols" in result

    def test_query_dependencies(self, tmp_path):
        """Dependencies запрос."""
        engine = GraphRAGQueryEngine(tmp_path)
        result = engine.query_dependencies("test_file.py")

        assert result["file"] == "test_file.py"
        assert "depends_on" in result
        assert "depended_by" in result

    def test_query_tests(self, tmp_path):
        """Tests запрос."""
        engine = GraphRAGQueryEngine(tmp_path)
        tests = engine.query_tests("test_file.py")

        assert isinstance(tests, list)

    def test_find_related_tests(self, tmp_path):
        """Поиск связанных тестов."""
        engine = GraphRAGQueryEngine(tmp_path)

        # Create tests directory
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_searcher.py").write_text("# test")

        tests = engine._find_related_tests(["src/core/searcher.py"])
        assert isinstance(tests, list)

    def test_query_hotspots_no_memory(self, tmp_path):
        """Hotspots без commit_memory."""
        engine = GraphRAGQueryEngine(tmp_path)
        result = engine.query_hotspots()

        assert result == []

    def test_query_similar_bugs_no_memory(self, tmp_path):
        """Similar bugs без commit_memory."""
        engine = GraphRAGQueryEngine(tmp_path)
        result = engine.query_similar_bugs("test error")

        assert result == []
