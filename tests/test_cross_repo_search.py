"""
Тесты для Cross-repo Search (MultiProjectSearcher).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.multi_project_searcher import (
    MultiProjectSearcher,
    ProjectRegistry,
    parse_cross_repo_query,
)


class TestParseCrossRepoQuery:
    """Тесты для разбора @-mention синтаксиса."""

    def test_no_mentions(self):
        query, projects = parse_cross_repo_query("authentication login")
        assert query == "authentication login"
        assert projects == []

    def test_single_mention(self):
        query, projects = parse_cross_repo_query("auth @backend")
        assert query == "auth"
        assert projects == ["backend"]

    def test_multiple_mentions(self):
        query, projects = parse_cross_repo_query("auth @backend @frontend @shared")
        assert query == "auth"
        assert projects == ["backend", "frontend", "shared"]

    def test_mention_at_start(self):
        query, projects = parse_cross_repo_query("@shared utils")
        assert query == "utils"
        assert projects == ["shared"]

    def test_mention_with_dashes(self):
        query, projects = parse_cross_repo_query("query @my-project @another-project")
        assert query == "query"
        assert projects == ["my-project", "another-project"]

    def test_mention_with_dots(self):
        query, projects = parse_cross_repo_query("query @project.v2")
        assert query == "query"
        assert projects == ["project.v2"]

    def test_only_mentions(self):
        query, projects = parse_cross_repo_query("@backend @frontend")
        assert query == ""
        assert projects == ["backend", "frontend"]

    def test_double_space_cleanup(self):
        query, projects = parse_cross_repo_query("hello  @backend  world")
        assert "  " not in query
        assert query == "hello world"


class TestProjectRegistry:
    """Тесты для реестра проектов."""

    def test_register_and_get(self):
        registry = ProjectRegistry()
        path = Path("/tmp/myproject")
        registry.register(path)
        assert registry.get("myproject") == path

    def test_unregister(self):
        registry = ProjectRegistry()
        path = Path("/tmp/myproject")
        registry.register(path)
        registry.unregister("myproject")
        assert registry.get("myproject") is None

    def test_get_nonexistent(self):
        registry = ProjectRegistry()
        assert registry.get("nonexistent") is None

    def test_find_by_prefix(self):
        registry = ProjectRegistry()
        registry.register(Path("/tmp/backend-api"))
        registry.register(Path("/tmp/backend-worker"))
        registry.register(Path("/tmp/frontend"))

        matches = registry.find_by_prefix("backend")
        assert len(matches) == 2
        names = [name for name, _ in matches]
        assert "backend-api" in names
        assert "backend-worker" in names

    def test_find_by_prefix_case_insensitive(self):
        registry = ProjectRegistry()
        registry.register(Path("/tmp/MyProject"))
        matches = registry.find_by_prefix("my")
        assert len(matches) == 1

    def test_list_projects(self):
        registry = ProjectRegistry()
        registry.register(Path("/tmp/a"))
        registry.register(Path("/tmp/b"))
        assert len(registry.list_projects()) == 2

    def test_count(self):
        registry = ProjectRegistry()
        assert registry.count == 0
        registry.register(Path("/tmp/a"))
        assert registry.count == 1


class TestMultiProjectSearcher:
    """Тесты для мультипроектного поиска."""

    def test_no_projects_registered(self):
        embedder = MagicMock()
        searcher = MultiProjectSearcher(embedder)
        result = searcher.search("test query")
        assert "Нет зарегистрированных проектов" in result

    def test_empty_query(self):
        embedder = MagicMock()
        registry = ProjectRegistry()
        registry.register(Path("/tmp/project"))
        searcher = MultiProjectSearcher(embedder, registry)
        result = searcher.search("@project")
        assert "Пустой" in result

    def test_cross_repo_search_with_mentions(self):
        """Проверяем что @-mentions правильно парсятся и передаются в cross_repo_search."""
        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 1024
        registry = ProjectRegistry()
        registry.register(Path("/tmp/backend"))
        registry.register(Path("/tmp/frontend"))
        searcher = MultiProjectSearcher(embedder, registry)

        # Мокаем _search_project чтобы не ходить в LanceDB
        with patch.object(searcher, "_search_project") as mock_search:
            mock_search.return_value = [
                {
                    "text": "def authenticate(): pass",
                    "metadata": {"file": "auth.py", "chunk_index": 0, "project": "backend"},
                    "score": 0.1,
                }
            ]
            results, meta = searcher.cross_repo_search(
                "auth", project_names=["backend"], limit=5
            )

        assert len(results) >= 1
        assert meta["projects_searched"] >= 1

    def test_merge_results_rrf(self):
        embedder = MagicMock()
        searcher = MultiProjectSearcher(embedder)

        project_results = {
            "backend": [
                {"text": "code1", "metadata": {"file": "a.py", "chunk_index": 0, "project": "backend"}, "score": 0.1},
                {"text": "code2", "metadata": {"file": "b.py", "chunk_index": 0, "project": "backend"}, "score": 0.2},
            ],
            "frontend": [
                {"text": "code3", "metadata": {"file": "c.py", "chunk_index": 0, "project": "frontend"}, "score": 0.15},
            ],
        }

        merged = searcher._merge_results_rrf(project_results, limit=5)
        assert len(merged) == 3  # Все 3 результата

    def test_merge_deduplication(self):
        """Один и тот же файл в разных проектах — не дубликат."""
        embedder = MagicMock()
        searcher = MultiProjectSearcher(embedder)

        project_results = {
            "backend": [
                {"text": "shared code", "metadata": {"file": "utils.py", "chunk_index": 0, "project": "backend"}, "score": 0.1},
            ],
            "frontend": [
                {"text": "shared code", "metadata": {"file": "utils.py", "chunk_index": 0, "project": "frontend"}, "score": 0.1},
            ],
        }

        merged = searcher._merge_results_rrf(project_results, limit=5)
        # Два результата из разных проектов — не дубликаты
        assert len(merged) == 2

    def test_search_formatted_output(self):
        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 1024
        registry = ProjectRegistry()
        registry.register(Path("/tmp/backend"))
        searcher = MultiProjectSearcher(embedder, registry)

        with patch.object(searcher, "cross_repo_search", return_value=(
            [
                {
                    "text": "def authenticate(): pass",
                    "metadata": {"file": "auth.py", "chunk_index": 0, "project": "backend"},
                    "rrf_score": 0.0167,
                    "source_projects": ["backend"],
                },
            ],
            {
                "projects_searched": 1,
                "projects_with_results": 1,
                "projects_names": ["backend"],
                "total_before_merge": 1,
                "total_after_merge": 1,
            },
        )):
            result = searcher.search("auth @backend")

        assert "Cross-repo" in result
        assert "backend" in result
        assert "auth.py" in result
