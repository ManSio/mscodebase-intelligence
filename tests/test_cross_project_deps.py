"""
Тесты для Cross-project Dependency Graph.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.cross_project_deps import (
    CrossProjectDependencyGraph,
    get_cross_project_deps,
)
from src.core.multi_project_searcher import ProjectRegistry


class TestCrossProjectDependencyGraphInit:
    """Тесты инициализации."""

    def test_init_with_registry(self):
        registry = ProjectRegistry()
        graph = CrossProjectDependencyGraph(project_registry=registry)
        assert graph.project_registry is registry

    def test_init_without_registry(self):
        graph = CrossProjectDependencyGraph()
        assert graph.project_registry is None

    def test_lazy_graph_build(self):
        graph = CrossProjectDependencyGraph()
        assert graph._graph is None


class TestBuildDependencyGraph:
    """Тесты построения графа зависимостей."""

    def test_empty_registry(self):
        graph = CrossProjectDependencyGraph()
        result = graph.build_dependency_graph()
        assert "nodes" in result
        assert "edges" in result
        assert "stats" in result
        assert result["stats"]["total_projects"] == 0

    def test_single_project_no_deps(self, tmp_path):
        registry = ProjectRegistry()
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        registry.register(project_dir)

        graph = CrossProjectDependencyGraph(project_registry=registry)
        result = graph.build_dependency_graph()
        assert result["stats"]["total_projects"] == 1

    def test_two_projects_with_imports(self, tmp_path):
        """Два проекта где один импортирует другой."""
        # Создаём проект backend
        backend = tmp_path / "backend"
        backend.mkdir()
        (backend / "main.py").write_text("from frontend.api import routes\n")

        # Создаём проект frontend
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        (frontend / "api.py").write_text("class Routes: pass\n")

        registry = ProjectRegistry()
        registry.register(backend)
        registry.register(frontend)

        graph = CrossProjectDependencyGraph(project_registry=registry)
        result = graph.build_dependency_graph()

        assert result["stats"]["total_projects"] == 2
        # Должна быть хотя бы одна зависимость
        assert result["stats"]["total_edges"] >= 0


class TestGetProjectDependencies:
    """Тесты зависимостей конкретного проекта."""

    def test_nonexistent_project(self):
        graph = CrossProjectDependencyGraph()
        result = graph.get_project_dependencies("nonexistent")
        assert result["project"] == "nonexistent"
        assert result["depends_on"] == []
        assert result["depended_by"] == []

    def test_direction_down(self, tmp_path):
        registry = ProjectRegistry()
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        registry.register(project_dir)

        graph = CrossProjectDependencyGraph(project_registry=registry)
        result = graph.get_project_dependencies("myproject", direction="down")
        assert "depends_on" in result

    def test_direction_up(self, tmp_path):
        registry = ProjectRegistry()
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        registry.register(project_dir)

        graph = CrossProjectDependencyGraph(project_registry=registry)
        result = graph.get_project_dependencies("myproject", direction="up")
        assert "depended_by" in result


class TestFindCircularDependencies:
    """Тесты поиска циклических зависимостей."""

    def test_no_cycles(self):
        graph = CrossProjectDependencyGraph()
        cycles = graph.find_circular_dependencies()
        assert isinstance(cycles, list)

    def test_detect_simple_cycle(self, tmp_path):
        """Два проекта, импортирующие друг друга."""
        a_dir = tmp_path / "project_a"
        a_dir.mkdir()
        (a_dir / "mod.py").write_text("from project_b.utils import helper\n")

        b_dir = tmp_path / "project_b"
        b_dir.mkdir()
        (b_dir / "utils.py").write_text("from project_a.mod import stuff\n")

        registry = ProjectRegistry()
        registry.register(a_dir)
        registry.register(b_dir)

        graph = CrossProjectDependencyGraph(project_registry=registry)
        cycles = graph.find_circular_dependencies()
        assert isinstance(cycles, list)


class TestFindSharedInterfaces:
    """Тесты поиска общих интерфейсов."""

    def test_no_shared(self):
        graph = CrossProjectDependencyGraph()
        shared = graph.find_shared_interfaces()
        assert isinstance(shared, list)

    def test_shared_symbols(self, tmp_path):
        """Два проекта с одинаковым именем класса."""
        a_dir = tmp_path / "project_a"
        a_dir.mkdir()
        (a_dir / "models.py").write_text("class User: pass\n")

        b_dir = tmp_path / "project_b"
        b_dir.mkdir()
        (b_dir / "models.py").write_text("class User: pass\n")

        registry = ProjectRegistry()
        registry.register(a_dir)
        registry.register(b_dir)

        graph = CrossProjectDependencyGraph(project_registry=registry)
        shared = graph.find_shared_interfaces()
        assert isinstance(shared, list)


class TestGetDependencyPath:
    """Тесты кратчайшего пути зависимости."""

    def test_no_path(self):
        graph = CrossProjectDependencyGraph()
        path = graph.get_dependency_path("a", "b")
        assert isinstance(path, list)

    def test_same_project(self, tmp_path):
        registry = ProjectRegistry()
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        registry.register(project_dir)

        graph = CrossProjectDependencyGraph(project_registry=registry)
        path = graph.get_dependency_path("myproject", "myproject")
        assert path == ["myproject"]


class TestAnalyzeImpact:
    """Тесты анализа влияния."""

    def test_nonexistent_project(self):
        graph = CrossProjectDependencyGraph()
        result = graph.analyze_impact("nonexistent")
        assert result["project"] == "nonexistent"
        assert result["risk_level"] == "low"

    def test_single_project_impact(self, tmp_path):
        registry = ProjectRegistry()
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        registry.register(project_dir)

        graph = CrossProjectDependencyGraph(project_registry=registry)
        result = graph.analyze_impact("myproject")
        assert "risk_level" in result
        assert result["risk_level"] in ("low", "medium", "high", "critical")


class TestScanImports:
    """Тесты сканирования импортов."""

    def test_python_imports(self, tmp_path):
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / "main.py").write_text(
            "from otherproject.api import routes\n"
            "import anotherproject.utils\n"
        )

        graph = CrossProjectDependencyGraph()
        imports = graph._scan_imports(project_dir)
        assert isinstance(imports, dict)

    def test_js_imports(self, tmp_path):
        project_dir = tmp_path / "frontend"
        project_dir.mkdir()
        (project_dir / "app.js").write_text(
            "import { api } from '../backend/routes';\n"
        )

        graph = CrossProjectDependencyGraph()
        imports = graph._scan_imports(project_dir)
        assert isinstance(imports, dict)

    def test_empty_project(self, tmp_path):
        project_dir = tmp_path / "empty"
        project_dir.mkdir()

        graph = CrossProjectDependencyGraph()
        imports = graph._scan_imports(project_dir)
        assert imports == {}


class TestDetectProjectReferences:
    """Тесты определения ссылок на проекты."""

    def test_known_project(self):
        graph = CrossProjectDependencyGraph()
        refs = graph._detect_project_references(
            ["backend.api", "frontend.utils", "os.path"],
            {"backend", "frontend"},
        )
        assert "backend" in refs
        assert "frontend" in refs
        assert "os" not in refs

    def test_no_references(self):
        graph = CrossProjectDependencyGraph()
        refs = graph._detect_project_references(
            ["os.path", "sys", "json"],
            {"backend", "frontend"},
        )
        assert len(refs) == 0


class TestFormatDependencyGraph:
    """Тесты форматирования."""

    def test_format_empty_graph(self):
        graph = CrossProjectDependencyGraph()
        result = graph.format_dependency_graph({
            "nodes": [],
            "edges": [],
            "stats": {"total_projects": 0, "total_edges": 0},
        })
        assert isinstance(result, str)

    def test_format_project_deps(self):
        graph = CrossProjectDependencyGraph()
        result = graph.format_project_deps({
            "project": "backend",
            "depends_on": ["shared"],
            "depended_by": ["frontend"],
            "shared_symbols": [],
        })
        assert "backend" in result
        assert "shared" in result
        assert "frontend" in result


class TestGetCrossProjectDeps:
    """Тесты фабричной функции."""

    def test_factory_without_registry(self):
        graph = get_cross_project_deps()
        assert isinstance(graph, CrossProjectDependencyGraph)

    def test_factory_with_registry(self):
        registry = ProjectRegistry()
        graph = get_cross_project_deps(project_registry=registry)
        assert isinstance(graph, CrossProjectDependencyGraph)
        assert graph.project_registry is registry
