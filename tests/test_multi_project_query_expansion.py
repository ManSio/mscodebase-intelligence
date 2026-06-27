"""
Smoke-тесты для MultiProjectSearcher, parse_cross_repo_query и query_expansion.

Не требуют запущенного эмбеддера или базы данных — тестируют парсинг и логику.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Гарантируем корректный sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# parse_cross_repo_query
# ---------------------------------------------------------------------------

class TestParseCrossRepoQuery:
    """Тесты парсинга @-mention синтаксиса."""

    def test_no_mentions(self):
        from src.core.multi_project_searcher import parse_cross_repo_query

        clean, projects = parse_cross_repo_query("auth handler")
        assert clean == "auth handler"
        assert projects == []

    def test_single_mention(self):
        from src.core.multi_project_searcher import parse_cross_repo_query

        clean, projects = parse_cross_repo_query("auth @backend")
        assert clean == "auth"
        assert projects == ["backend"]

    def test_multiple_mentions(self):
        from src.core.multi_project_searcher import parse_cross_repo_query

        clean, projects = parse_cross_repo_query("database @backend @shared")
        assert clean == "database"
        assert projects == ["backend", "shared"]

    def test_only_mention(self):
        from src.core.multi_project_searcher import parse_cross_repo_query

        clean, projects = parse_cross_repo_query("@backend")
        assert clean == ""
        assert projects == ["backend"]

    def test_extra_spaces(self):
        from src.core.multi_project_searcher import parse_cross_repo_query

        clean, projects = parse_cross_repo_query("  auth   @backend   @frontend  ")
        assert clean == "auth"
        assert projects == ["backend", "frontend"]

    def test_prefix_notation(self):
        from src.core.multi_project_searcher import parse_cross_repo_query

        # @shared должен матчить по префиксу внутри ProjectRegistry,
        # но parse_cross_repo_query просто извлекает имя
        clean, projects = parse_cross_repo_query("utils @shared")
        assert clean == "utils"
        assert projects == ["shared"]


# ---------------------------------------------------------------------------
# ProjectRegistry
# ---------------------------------------------------------------------------

class TestProjectRegistry:
    """Тесты реестра проектов."""

    def test_register_and_get(self, tmp_path):
        from src.core.multi_project_searcher import ProjectRegistry

        reg = ProjectRegistry()
        reg.register(tmp_path / "backend")
        assert reg.get("backend") == tmp_path / "backend"

    def test_unregister(self, tmp_path):
        from src.core.multi_project_searcher import ProjectRegistry

        reg = ProjectRegistry()
        reg.register(tmp_path / "backend")
        reg.unregister("backend")
        assert reg.get("backend") is None

    def test_find_by_prefix(self, tmp_path):
        from src.core.multi_project_searcher import ProjectRegistry

        reg = ProjectRegistry()
        reg.register(tmp_path / "backend")
        reg.register(tmp_path / "backend-api")
        reg.register(tmp_path / "frontend")

        matches = reg.find_by_prefix("backend")
        names = [name for name, _ in matches]
        assert "backend" in names
        assert "backend-api" in names
        assert "frontend" not in names

    def test_list_projects(self, tmp_path):
        from src.core.multi_project_searcher import ProjectRegistry

        reg = ProjectRegistry()
        reg.register(tmp_path / "a")
        reg.register(tmp_path / "b")
        assert reg.count == 2
        assert len(reg.list_projects()) == 2

    def test_count(self):
        from src.core.multi_project_searcher import ProjectRegistry

        reg = ProjectRegistry()
        assert reg.count == 0


# ---------------------------------------------------------------------------
# MultiProjectSearcher — _merge_results_rrf
# ---------------------------------------------------------------------------

class TestMergeResultsRRF:
    """Тест слияния результатов через RRF."""

    def test_merge_single_project(self):
        from src.core.multi_project_searcher import MultiProjectSearcher

        searcher = MultiProjectSearcher(embedder=MagicMock())
        project_results = {
            "proj_a": [
                {
                    "text": "chunk1",
                    "metadata": {"file": "f1.py", "chunk_index": 0, "project": "proj_a"},
                    "score": 0.9,
                },
                {
                    "text": "chunk2",
                    "metadata": {"file": "f2.py", "chunk_index": 0, "project": "proj_a"},
                    "score": 0.8,
                },
            ]
        }
        merged = searcher._merge_results_rrf(project_results, limit=8, rrf_k=60)
        assert len(merged) == 2
        # Первый результат должен иметь высший rrf_score
        assert merged[0]["metadata"]["file"] == "f1.py"

    def test_merge_multiple_projects(self):
        from src.core.multi_project_searcher import MultiProjectSearcher

        searcher = MultiProjectSearcher(embedder=MagicMock())
        project_results = {
            "proj_a": [
                {
                    "text": "a_chunk",
                    "metadata": {"file": "fa.py", "chunk_index": 0, "project": "proj_a"},
                    "score": 0.9,
                },
            ],
            "proj_b": [
                {
                    "text": "b_chunk",
                    "metadata": {"file": "fb.py", "chunk_index": 0, "project": "proj_b"},
                    "score": 0.95,
                },
            ],
        }
        merged = searcher._merge_results_rrf(project_results, limit=8, rrf_k=60)
        assert len(merged) == 2
        # Оба должны иметь rrf_score = 1/(60+1)
        for r in merged:
            assert r["rrf_score"] == pytest.approx(1.0 / 61)

    def test_merge_limit(self):
        from src.core.multi_project_searcher import MultiProjectSearcher

        searcher = MultiProjectSearcher(embedder=MagicMock())
        project_results = {
            "proj": [
                {
                    "text": f"chunk{i}",
                    "metadata": {"file": f"f{i}.py", "chunk_index": i, "project": "proj"},
                    "score": 1.0 - i * 0.1,
                }
                for i in range(10)
            ]
        }
        merged = searcher._merge_results_rrf(project_results, limit=3, rrf_k=60)
        assert len(merged) == 3


# ---------------------------------------------------------------------------
# MultiProjectSearcher — search() без реальных проектов
# ---------------------------------------------------------------------------

class TestMultiProjectSearcherSearch:
    """Тесты метода search() без подключения к БД."""

    def test_empty_registry_returns_error(self):
        from src.core.multi_project_searcher import MultiProjectSearcher

        searcher = MultiProjectSearcher(embedder=MagicMock())
        result = searcher.search("anything")
        assert "Нет зарегистрированных проектов" in result

    def test_empty_query_after_parse(self, tmp_path):
        from src.core.multi_project_searcher import MultiProjectSearcher

        searcher = MultiProjectSearcher(embedder=MagicMock())
        searcher.registry.register(tmp_path / "test_project")
        result = searcher.search("@test_project")
        assert "Пустой поисковый запрос" in result


# ---------------------------------------------------------------------------
# query_expansion
# ---------------------------------------------------------------------------

class TestQueryExpansion:
    """Тесты расширения запросов."""

    def test_empty_query(self):
        from src.core.query_expansion import expand_query

        result = expand_query("")
        assert result == [""]

    def test_synonym_expansion(self):
        from src.core.query_expansion import expand_query

        result = expand_query("auth")
        # Должен содержать оригинал + синонимы
        assert "auth" in result
        # Хотя бы один синоним должен появиться
        all_words = " ".join(result)
        assert "authentication" in all_words or "login" in all_words

    def test_max_expansions(self):
        from src.core.query_expansion import expand_query

        result = expand_query("auth handler service", max_expansions=3)
        assert len(result) <= 3

    def test_stemming(self):
        from src.core.query_expansion import expand_query

        result = expand_query("validation")
        # Должен содержать вариант без окончания
        assert any("valid" in r for r in result)

    def test_plural_singular(self):
        from src.core.query_expansion import expand_query

        result = expand_query("handlers")
        # Должен содержать единственное число
        assert any("handler" in r.split() for r in result)

    def test_get_search_suggestions(self):
        from src.core.query_expansion import get_search_suggestions

        suggestions = get_search_suggestions("auth handler")
        assert len(suggestions) >= 1
        assert any("Попробуйте:" in s for s in suggestions)

    def test_get_search_suggestions_no_match(self):
        from src.core.query_expansion import get_search_suggestions

        suggestions = get_search_suggestions("xyzqwerty")
        assert suggestions == []


# ---------------------------------------------------------------------------
# StructuralSearcher — list_patterns и format_results
# ---------------------------------------------------------------------------

class TestStructuralSearcherSmoke:
    """Smoke-тесты для StructuralSearcher без реального парсинга файлов."""

    def test_list_patterns(self):
        from src.core.structural_search import StructuralSearcher

        searcher = StructuralSearcher()
        patterns = searcher.list_patterns()
        assert isinstance(patterns, dict)
        assert len(patterns) > 0
        # Проверяем что известные паттерны на месте
        assert "class_inheritance" in patterns
        assert "function_with_decorator" in patterns

    def test_format_results_empty(self):
        from src.core.structural_search import StructuralSearcher, SearchResult

        searcher = StructuralSearcher()
        sr = SearchResult(pattern="test")
        formatted = searcher.format_results(sr)
        assert isinstance(formatted, str)
        assert "test" in formatted
