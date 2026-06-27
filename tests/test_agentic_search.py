"""
Тесты для Agentic Code Search.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.searcher import Searcher


class TestDecomposeQueryWithLLM:
    """Тесты для _decompose_query_with_llm."""

    def test_simple_query_unchanged(self):
        """Простой запрос не должен разбиваться."""
        searcher = Searcher(MagicMock(), MagicMock())
        result = searcher._decompose_query_with_llm("authentication")
        assert len(result) == 1
        assert "authentication" in result[0]

    def test_split_by_and(self):
        """Разделение по 'и'."""
        searcher = Searcher(MagicMock(), MagicMock())
        result = searcher._decompose_query_with_llm("авторизация и проверка прав")
        assert len(result) == 2
        assert any("авторизация" in r for r in result)
        assert any("проверка прав" in r for r in result)

    def test_split_by_comma(self):
        """Разделение по запятой."""
        searcher = Searcher(MagicMock(), MagicMock())
        result = searcher._decompose_query_with_llm("авторизация, проверка прав")
        assert len(result) >= 2

    def test_split_by_question_words(self):
        """Разделение по 'как' и 'где'."""
        searcher = Searcher(MagicMock(), MagicMock())
        result = searcher._decompose_query_with_llm("как работает авторизация и где проверяются права")
        assert len(result) >= 2
        assert any("как работает" in r for r in result)
        assert any("где" in r for r in result)

    def test_max_subqueries_limit(self):
        """Не более 4 подзапросов."""
        searcher = Searcher(MagicMock(), MagicMock())
        result = searcher._decompose_query_with_llm(
            "авторизация и регистрация и проверка прав и логирование и аудит"
        )
        assert len(result) <= 4

    def test_short_parts_filtered(self):
        """Короткие части (< 4 символов) должны быть отфильтрованы."""
        searcher = Searcher(MagicMock(), MagicMock())
        result = searcher._decompose_query_with_llm("auth и и и и")
        for r in result:
            assert len(r) > 3

    def test_empty_query(self):
        """Пустой запрос."""
        searcher = Searcher(MagicMock(), MagicMock())
        result = searcher._decompose_query_with_llm("")
        assert len(result) == 1
        assert result[0] == ""


class TestAnalyzeSubqueryRelations:
    """Тесты для _analyze_subquery_relations."""

    def test_no_common_files(self):
        searcher = Searcher(MagicMock(), MagicMock())
        subqueries = ["auth", "logging"]
        results = {
            "auth": [
                {"metadata": {"file": "auth.py", "chunk_index": 0}, "text": "auth code"}
            ],
            "logging": [
                {"metadata": {"file": "log.py", "chunk_index": 0}, "text": "log code"}
            ],
        }
        analysis = searcher._analyze_subquery_relations(subqueries, results)
        assert analysis["common_files"] == []

    def test_common_files_detected(self):
        searcher = Searcher(MagicMock(), MagicMock())
        subqueries = ["auth", "permissions"]
        results = {
            "auth": [
                {"metadata": {"file": "utils.py", "chunk_index": 0}, "text": "utils"},
                {"metadata": {"file": "auth.py", "chunk_index": 0}, "text": "auth"},
            ],
            "permissions": [
                {"metadata": {"file": "utils.py", "chunk_index": 1}, "text": "utils"},
                {"metadata": {"file": "perms.py", "chunk_index": 0}, "text": "perms"},
            ],
        }
        analysis = searcher._analyze_subquery_relations(subqueries, results)
        assert "utils.py" in analysis["common_files"]

    def test_coverage_score(self):
        searcher = Searcher(MagicMock(), MagicMock())
        subqueries = ["a", "b"]
        results = {
            "a": [
                {"metadata": {"file": "f1.py", "chunk_index": 0}, "text": "x"},
                {"metadata": {"file": "f2.py", "chunk_index": 0}, "text": "x"},
            ],
            "b": [
                {"metadata": {"file": "f3.py", "chunk_index": 0}, "text": "x"},
            ],
        }
        analysis = searcher._analyze_subquery_relations(subqueries, results)
        assert analysis["coverage_score"] > 0

    def test_flow_description_generated(self):
        searcher = Searcher(MagicMock(), MagicMock())
        subqueries = ["auth", "logging"]
        results = {
            "auth": [
                {"metadata": {"file": "auth.py", "chunk_index": 0}, "text": "auth"}
            ],
            "logging": [
                {"metadata": {"file": "log.py", "chunk_index": 0}, "text": "log"}
            ],
        }
        analysis = searcher._analyze_subquery_relations(subqueries, results)
        assert "2 подзапросов" in analysis["flow_description"]


class TestAgenticCodeSearch:
    """Тесты для agentic_code_search."""

    def test_simple_query_uses_hybrid_search(self):
        """Простой запрос использует обычный hybrid_search."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        mock_results = [
            {"metadata": {"file": "a.py", "chunk_index": 0}, "text": "code", "final_score": 0.8}
        ]
        with patch.object(searcher, "hybrid_search", return_value=mock_results):
            results, meta = searcher.agentic_code_search("simple query")

        assert len(results) == 1
        assert len(meta["subqueries"]) == 1

    def test_complex_query_decomposes_and_searches(self):
        """Сложный запрос разбивается и ищется по частям."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        # Мокаем hybrid_search для разных подзапросов
        call_count = 0

        def mock_hybrid_search(query, **kwargs):
            nonlocal call_count
            call_count += 1
            return [
                {"metadata": {"file": f"file{call_count}.py", "chunk_index": 0}, "text": f"code {query}", "final_score": 0.9}
            ]

        with patch.object(searcher, "hybrid_search", side_effect=mock_hybrid_search):
            results, meta = searcher.agentic_code_search(
                "как работает авторизация и где проверяются права"
            )

        # Должно быть несколько подзапросов
        assert len(meta["subqueries"]) >= 2
        # Должно быть несколько вызовов hybrid_search
        assert call_count >= 2

    def test_deduplication_across_subqueries(self):
        """Дедупликация результатов между подзапросами."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        same_result = {"metadata": {"file": "shared.py", "chunk_index": 0}, "text": "shared code", "final_score": 0.8}

        with patch.object(searcher, "hybrid_search", return_value=[same_result]):
            results, meta = searcher.agentic_code_search(
                "auth и permissions"
            )

        # Один и тот же результат не должен быть дублирован
        keys = [f"{r['metadata']['file']}:{r['metadata']['chunk_index']}" for r in results]
        assert len(keys) == len(set(keys))

    def test_relations_analyzed(self):
        """Анализ связей между результатами."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        with patch.object(searcher, "hybrid_search", return_value=[
            {"metadata": {"file": "a.py", "chunk_index": 0}, "text": "code", "final_score": 0.8}
        ]):
            _, meta = searcher.agentic_code_search("auth и perms")

        assert meta["relations"] is not None
        assert "coverage_score" in meta["relations"]

    def test_max_total_results_limit(self):
        """Ограничение на итоговое число результатов."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        # Возвращаем много результатов
        many_results = [
            {"metadata": {"file": f"f{i}.py", "chunk_index": 0}, "text": f"code {i}", "final_score": 0.9 - i * 0.01}
            for i in range(20)
        ]

        with patch.object(searcher, "hybrid_search", return_value=many_results):
            results, _ = searcher.agentic_code_search(
                "auth и perms", max_total_results=5
            )

        assert len(results) <= 5
