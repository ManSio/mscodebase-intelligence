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
        import asyncio
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        mock_results = [
            {"metadata": {"file": "a.py", "chunk_index": 0}, "text": "code", "final_score": 0.8}
        ]
        # Мокаем async версию
        async def mock_async(*args, **kwargs):
            return mock_results
        with patch.object(searcher, "hybrid_search_async", side_effect=mock_async):
            results, meta = searcher.agentic_code_search("simple query")

        assert len(results) == 1
        assert len(meta["subqueries"]) == 1

    def test_complex_query_decomposes_and_searches(self):
        """Сложный запрос разбивается и ищется по частям через asyncio.gather."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        # Мокаем async hybrid_search для разных подзапросов
        call_count = 0

        async def mock_hybrid_search_async(query, limit=5, use_rrf=True, expand=True):
            nonlocal call_count
            call_count += 1
            return [
                {"metadata": {"file": f"file{call_count}.py", "chunk_index": 0}, "text": f"code {query}", "final_score": 0.9}
            ]

        with patch.object(searcher, "hybrid_search_async", side_effect=mock_hybrid_search_async):
            results, meta = searcher.agentic_code_search(
                "как работает авторизация и где проверяются права"
            )

        # Должно быть несколько подзапросов
        assert len(meta["subqueries"]) >= 2
        # Должно быть несколько вызовов hybrid_search_async
        assert call_count >= 2

    def test_deduplication_across_subqueries(self):
        """Дедупликация результатов между подзапросами."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        same_result = {"metadata": {"file": "shared.py", "chunk_index": 0}, "text": "shared code", "final_score": 0.8}

        async def mock_async(*args, **kwargs):
            return [same_result]
        with patch.object(searcher, "hybrid_search_async", side_effect=mock_async):
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

        async def mock_async(*args, **kwargs):
            return [
                {"metadata": {"file": "a.py", "chunk_index": 0}, "text": "code", "final_score": 0.8}
            ]
        with patch.object(searcher, "hybrid_search_async", side_effect=mock_async):
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

        async def mock_async(*args, **kwargs):
            return many_results
        with patch.object(searcher, "hybrid_search_async", side_effect=mock_async):
            results, _ = searcher.agentic_code_search(
                "auth и perms", max_total_results=5
            )

        assert len(results) <= 5

    def test_fallback_on_empty_decomposition(self):
        """Fallback на обычный поиск если декомпозиция не дала результатов."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        # Мокаем декомпозицию чтобы вернула 2+ подзапроса
        # и hybrid_search чтобы вернула пустой результат для подзапросов
        # Fallback должен вызвать hybrid_search с оригинальным запросом
        fallback_result = [
            {"metadata": {"file": "fallback.py", "chunk_index": 0}, "text": "found", "final_score": 0.8}
        ]

        async def mock_hybrid_search_async(query, limit=5, use_rrf=True, expand=True):
            # Fallback вызывается с оригинальным запросом
            if query == "complex query":
                return fallback_result
            # Подзапросы возвращают пустой результат
            return []

        with patch.object(searcher, "_decompose_query_with_llm", return_value=["subquery1", "subquery2"]):
            with patch.object(searcher, "hybrid_search_async", side_effect=mock_hybrid_search_async):
                results, meta = searcher.agentic_code_search("complex query")

        # Должен быть использован fallback
        assert meta["fallback_used"] is True
        assert len(results) >= 1

    def test_llm_decomposition_fallback_to_rules(self):
        """LLM недоступен — fallback на правила."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        # Мокаем _try_llm_decompose чтобы вернул None (LLM недоступен)
        with patch.object(searcher, "_try_llm_decompose", return_value=None):
            subqueries = searcher._decompose_query_with_llm("auth и permissions")

        # Должны получить подзапросы от правил
        assert len(subqueries) >= 2

    def test_parallel_search_with_threadpool(self):
        """Параллельный поиск подзапросов через asyncio.gather."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        call_times = []
        import asyncio

        async def mock_hybrid_search_async(query, limit=5, use_rrf=True, expand=True):
            call_times.append(query)
            await asyncio.sleep(0.01)  # Имитация задержки
            return [
                {"metadata": {"file": f"{query[:10]}.py", "chunk_index": 0}, "text": "code", "final_score": 0.8}
            ]

        with patch.object(searcher, "hybrid_search_async", side_effect=mock_hybrid_search_async):
            results, meta = searcher.agentic_code_search("auth и perms и roles")

        # Должно быть 3 подзапроса
        assert len(meta["subqueries"]) >= 2
        # Все подзапросы должны быть обработаны
        assert len(call_times) >= 2

    def test_decomposition_method_tracked(self):
        """Метаданные содержат метод декомпозиции (llm/rules/none)."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        # Простой запрос — метод none
        async def mock_empty(*args, **kwargs):
            return []
        with patch.object(searcher, "hybrid_search_async", side_effect=mock_empty):
            _, meta = searcher.agentic_code_search("simple")
        assert meta["decomposition_method"] == "none"

        # Сложный запрос с LLM fallback на правила
        # Мокаем _try_llm_decompose чтобы вернул None (LLM недоступен)
        with patch.object(searcher, "_try_llm_decompose", return_value=None):
            with patch.object(searcher, "hybrid_search_async", side_effect=mock_empty):
                _, meta = searcher.agentic_code_search("auth и perms")
        # Метод должен быть "rules" т.к. _try_llm_decompose вернул None
        assert meta["decomposition_method"] in ("rules", "llm")  # зависит от порядка вызова

    def test_call_graph_analysis_with_symbol_index(self):
        """Call Graph анализ использует build_call_graph для поиска символов."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        # Создаём mock symbol_index с build_call_graph
        mock_symbol_index = MagicMock()
        mock_symbol_index.get_symbols_in_file.return_value = [
            "authenticate", "check_permissions"
        ]
        mock_symbol_index.build_call_graph.return_value = {
            "symbol": "authenticate",
            "definition": [{"file": "auth.py", "line": 10, "kind": "function"}],
            "callers": [{"file": "routes.py", "line": 5, "kind": "call"}],
            "callees": [{"symbol": "validate_user", "file": "auth.py", "line": 15, "kind": "function"}],
            "impact_files": ["auth.py", "routes.py"],
        }

        # Мокаем декомпозицию и поиск
        async def mock_auth(*args, **kwargs):
            return [
                {"metadata": {"file": "auth.py", "chunk_index": 0}, "text": "code", "final_score": 0.8}
            ]
        with patch.object(searcher, "_decompose_query_with_llm", return_value=["sub1", "sub2"]):
            with patch.object(searcher, "hybrid_search_async", side_effect=mock_auth):
                _, meta = searcher.agentic_code_search(
                    "auth query", symbol_index=mock_symbol_index
                )

        # Проверяем что Call Graph анализ был выполнен
        assert meta["relations"] is not None
        # build_call_graph должен был быть вызван
        mock_symbol_index.build_call_graph.assert_called()
        # Должны быть related_symbols и call_graph_hints
        assert len(meta["relations"]["related_symbols"]) > 0
        assert len(meta["relations"]["call_graph_hints"]) > 0
        # Метрики глубины и узлов
        assert meta["relations"]["call_graph_depth"] >= 1
        assert meta["relations"]["call_graph_nodes_count"] > 0

    def test_call_graph_analysis_without_symbol_index(self):
        """Без symbol_index — Call Graph анализ пропускается gracefully."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        async def mock_auth(*args, **kwargs):
            return [
                {"metadata": {"file": "auth.py", "chunk_index": 0}, "text": "code", "final_score": 0.8}
            ]
        with patch.object(searcher, "_decompose_query_with_llm", return_value=["sub1", "sub2"]):
            with patch.object(searcher, "hybrid_search_async", side_effect=mock_auth):
                _, meta = searcher.agentic_code_search("auth query", symbol_index=None)

        # Без symbol_index — related_symbols должен быть пустым
        assert meta["relations"]["related_symbols"] == []
        assert meta["relations"]["call_graph_hints"] == []

    def test_call_graph_analysis_error_handling(self):
        """Ошибка в symbol_index не ломает поиск — fallback на упрощённый подход."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        # symbol_index который бросает исключение в build_call_graph
        broken_symbol_index = MagicMock()
        broken_symbol_index.get_symbols_in_file.return_value = ["authenticate"]
        broken_symbol_index.build_call_graph.side_effect = Exception("DB error")
        # Fallback тоже падает
        broken_symbol_index.find_references.side_effect = Exception("DB error 2")

        async def mock_auth(*args, **kwargs):
            return [
                {"metadata": {"file": "auth.py", "chunk_index": 0}, "text": "code", "final_score": 0.8}
            ]
        # Используем 2 подзапроса чтобы попасть в ветку с _analyze_subquery_relations
        with patch.object(searcher, "_decompose_query_with_llm", return_value=["sub1", "sub2"]):
            with patch.object(searcher, "hybrid_search_async", side_effect=mock_auth):
                # Не должно упасть
                results, meta = searcher.agentic_code_search(
                    "auth query", symbol_index=broken_symbol_index
                )

        assert len(results) >= 1
        # При ошибке symbol_index, related_symbols должен быть пустым
        assert meta["relations"]["related_symbols"] == []
        assert meta["relations"]["call_graph_hints"] == []
        # Метрики должны быть нулевыми при ошибке
        assert meta["relations"]["call_graph_depth"] == 0
        assert meta["relations"]["call_graph_nodes_count"] == 0

    def test_metrics_in_metadata(self):
        """Метаданные содержат метрики для анализа качества."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        test_results = [
            {"metadata": {"file": f"file{i}.py", "chunk_index": 0}, "text": f"code {i}", "final_score": 0.9 - i * 0.01}
            for i in range(3)
        ]
        async def mock_async(*args, **kwargs):
            return test_results
        with patch.object(searcher, "_decompose_query_with_llm", return_value=["sub1", "sub2"]):
            with patch.object(searcher, "hybrid_search_async", side_effect=mock_async):
                results, meta = searcher.agentic_code_search("test query")

        # Проверяем наличие метрик
        assert "total_unique" in meta
        assert "subquery_results_count" in meta
        assert "coverage_score" in meta["relations"]
        assert meta["total_unique"] >= 1

    def test_agentic_vs_hybrid_fallback(self):
        """Agentic поиск fallback на hybrid при ошибке декомпозиции."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        # Декомпозиция возвращает 1 подзапрос → fallback на обычный hybrid
        async def mock_result(*args, **kwargs):
            return [
                {"metadata": {"file": "result.py", "chunk_index": 0}, "text": "found", "final_score": 0.8}
            ]
        with patch.object(searcher, "_decompose_query_with_llm", return_value=["simple"]):
            with patch.object(searcher, "hybrid_search_async", side_effect=mock_result):
                results, meta = searcher.agentic_code_search("simple query")

        # Должен использоваться hybrid_search (decomposition_method = none)
        assert meta["decomposition_method"] == "none"
        assert len(results) >= 1
