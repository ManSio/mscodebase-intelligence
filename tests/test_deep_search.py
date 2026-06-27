"""
Тесты для Agentic Deep Search.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.searcher import Searcher


def _make_result(file_path: str, chunk_index: int, text: str, score: float = 0.5) -> dict:
    """Хелпер для создания результата поиска."""
    return {
        "text": text,
        "metadata": {"file": file_path, "chunk_index": chunk_index},
        "bm25_score": score * 0.3,
        "dense_score": score * 0.7,
        "final_score": score,
    }


class TestExtractKeyTerms:
    """Тесты для _extract_key_terms."""

    def test_empty_results(self):
        searcher = Searcher(MagicMock(), MagicMock())
        assert searcher._extract_key_terms([]) == []

    def test_extracts_significant_terms(self):
        searcher = Searcher(MagicMock(), MagicMock())
        results = [
            _make_result("a.py", 0, "def authenticate_user(username, password): return check_credentials(username, password)"),
            _make_result("b.py", 0, "def authenticate_user(email, token): return validate_token(email, token)"),
            _make_result("c.py", 0, "class UserAuthenticator: def authenticate_user(self, creds): pass"),
        ]
        terms = searcher._extract_key_terms(results, max_terms=5)
        # "authenticate_user" встречается во всех 3 документах — должен быть извлечён
        assert "authenticate_user" in terms

    def test_filters_stop_words(self):
        searcher = Searcher(MagicMock(), MagicMock())
        results = [
            _make_result("a.py", 0, "def foo(): return self is not None and True or False"),
            _make_result("b.py", 0, "def bar(): return self is not None and True or False"),
        ]
        terms = searcher._extract_key_terms(results, max_terms=5)
        # Стоп-слова не должны быть в результатах
        for stop in ("self", "none", "true", "false", "return"):
            assert stop not in terms

    def test_short_terms_filtered(self):
        """Термины короче 4 символов должны быть отфильтрованы."""
        searcher = Searcher(MagicMock(), MagicMock())
        results = [
            _make_result("a.py", 0, "x = get(y) if set(z) else put(w)"),
            _make_result("b.py", 0, "x = get(y) if set(z) else put(w)"),
        ]
        terms = searcher._extract_key_terms(results, max_terms=5)
        for t in terms:
            assert len(t) >= 4

    def test_max_terms_limit(self):
        searcher = Searcher(MagicMock(), MagicMock())
        results = [
            _make_result("a.py", 0, "alpha beta gamma delta epsilon zeta eta theta"),
            _make_result("b.py", 0, "alpha beta gamma delta epsilon zeta eta theta"),
        ]
        terms = searcher._extract_key_terms(results, max_terms=3)
        assert len(terms) <= 3


class TestGenerateRefinedQuery:
    """Тесты для _generate_refined_query."""

    def test_iteration_1_adds_terms(self):
        searcher = Searcher(MagicMock(), MagicMock())
        result = searcher._generate_refined_query("auth", ["login", "session", "token", "cookie"], 1)
        # Итерация 1: оригинальный запрос + топ-3 термина
        assert "auth" in result
        assert "login" in result
        assert "session" in result
        assert "token" in result
        # 4-й термин не должен быть добавлен
        assert "cookie" not in result

    def test_iteration_2_focuses_on_terms(self):
        searcher = Searcher(MagicMock(), MagicMock())
        result = searcher._generate_refined_query("auth", ["login", "session", "token", "cookie", "jwt", "extra"], 2)
        # Итерация 2: только ключевые термины (топ-5)
        assert "login" in result
        assert "session" in result
        assert "token" in result
        # Оригинальный запрос не должен быть в строке терминов
        # (он может совпасть с термином, но не добавляется отдельно)

    def test_empty_terms_returns_original(self):
        searcher = Searcher(MagicMock(), MagicMock())
        result = searcher._generate_refined_query("auth", [], 1)
        assert result == "auth"


class TestAgenticDeepSearch:
    """Тесты для agentic_deep_search."""

    def test_empty_index_returns_empty(self):
        """Пустой индекс должен вернуть пустой результат."""
        indexer = MagicMock()
        indexer.table = None
        embedder = MagicMock()
        embedder.embed.return_value = None
        searcher = Searcher(indexer, embedder)

        results, meta = searcher.agentic_deep_search("test query", max_iterations=2)
        assert results == []
        assert meta["iterations"] >= 1

    def test_single_iteration_enough_results(self):
        """Если первый поиск даёт достаточно результатов — ранняя остановка."""
        indexer = MagicMock()
        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 1024
        searcher = Searcher(indexer, embedder)

        # Мокаем hybrid_search чтобы вернуть достаточно результатов
        mock_results = [
            _make_result("a.py", i, f"def func_{i}(): pass", score=0.9 - i * 0.05)
            for i in range(8)
        ]
        with patch.object(searcher, "hybrid_search", return_value=mock_results):
            results, meta = searcher.agentic_deep_search(
                "test", max_iterations=3, max_total_results=8
            )

        assert len(results) >= 1
        assert meta["early_stop"] is True
        assert meta["iterations"] == 1  # Ранняя остановка на 1-й итерации

    def test_multiple_iterations_merge_results(self):
        """Результаты из разных итераций должны быть объединены."""
        indexer = MagicMock()
        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 1024
        searcher = Searcher(indexer, embedder)

        call_count = 0

        def mock_hybrid_search(query, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [_make_result("a.py", 0, "authentication login session", score=0.8)]
            else:
                return [_make_result("b.py", 0, "token validation check", score=0.7)]

        with patch.object(searcher, "hybrid_search", side_effect=mock_hybrid_search):
            results, meta = searcher.agentic_deep_search(
                "auth", max_iterations=2, max_total_results=5, limit_per_iteration=5
            )

        assert len(results) >= 2
        assert meta["iterations"] >= 2
        # Результаты из разных файлов
        files = {r["metadata"]["file"] for r in results}
        assert "a.py" in files
        assert "b.py" in files

    def test_deduplication_across_iterations(self):
        """Дубликаты из разных итераций должны быть удалены."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        same_result = _make_result("a.py", 0, "duplicate code", score=0.8)

        with patch.object(searcher, "hybrid_search", return_value=[same_result]):
            results, meta = searcher.agentic_deep_search(
                "test", max_iterations=2, max_total_results=5
            )

        # Тот же результат не должен быть дублирован
        keys = [f"{r['metadata']['file']}:{r['metadata']['chunk_index']}" for r in results]
        assert len(keys) == len(set(keys))

    def test_metadata_tracks_queries(self):
        """Метаданные должны отслеживать использованные запросы."""
        indexer = MagicMock()
        embedder = MagicMock()
        searcher = Searcher(indexer, embedder)

        mock_results = [_make_result("a.py", 0, "some code with interesting terms", score=0.8)]

        with patch.object(searcher, "hybrid_search", return_value=mock_results):
            _, meta = searcher.agentic_deep_search(
                "original query", max_iterations=2, max_total_results=5
            )

        assert len(meta["queries_used"]) >= 1
        assert "original query" in meta["queries_used"][0]


class TestDeepSearchMCP:
    """Тесты для deep_search (MCP-форматированный вывод)."""

    def test_empty_index_message(self):
        indexer = MagicMock()
        indexer.table = None
        embedder = MagicMock()
        embedder.embed.return_value = None
        searcher = Searcher(indexer, embedder)

        result = searcher.deep_search("test")
        assert "ничего не найдено" in result.lower() or "пуста" in result.lower()

    def test_formatted_output(self):
        indexer = MagicMock()
        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 1024
        searcher = Searcher(indexer, embedder)

        mock_results = [
            _make_result("auth.py", 0, "def authenticate(user, pwd): ...", score=0.85),
            _make_result("login.py", 1, "class LoginHandler: ...", score=0.72),
        ]

        with patch.object(searcher, "agentic_deep_search", return_value=(mock_results, {
            "iterations": 2,
            "queries_used": ["auth", "auth authenticate login"],
            "terms_extracted": ["authenticate", "login"],
            "total_unique": 2,
            "early_stop": False,
        })):
            result = searcher.deep_search("auth")

        assert "Agentic Deep Search" in result
        assert "auth.py" in result
        assert "login.py" in result
        assert "2 итераций" in result
