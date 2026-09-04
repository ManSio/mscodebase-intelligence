"""Unit and Integration tests for the Graph Symbol Resolver pass."""

import os
import tempfile
from pathlib import Path

import pytest

from src.core.graph import EdgeType, NodeLabel, PropertyGraph
from src.core.search.graph_resolver import (
    GraphSymbolResolver,
    get_module_dot_path,
    is_external_or_stdlib,
    resolve_relative_import,
)


@pytest.fixture
def pg():
    """Temporary PropertyGraph for testing."""
    fd, db_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_path = Path(db_path_str)
    graph = PropertyGraph(db_path)
    yield graph
    graph.close()
    db_path.unlink(missing_ok=True)


class TestGraphResolverHelper:
    """Tests helper functions in graph_resolver."""

    def test_get_module_dot_path(self):
        assert get_module_dot_path("src/core/search/graph_adapter.py") == "src.core.search.graph_adapter"
        assert get_module_dot_path("tests/test_parser.py") == "tests.test_parser"
        assert get_module_dot_path("./src/main.py") == "src.main"

    def test_resolve_relative_import(self):
        # relative to src.core.search.graph_adapter_pure
        base = "src.core.search.graph_adapter_pure"
        assert resolve_relative_import(base, ".graph_adapter.Symbol") == "src.core.search.graph_adapter.Symbol"
        assert resolve_relative_import(base, "..graph.Graph") == "src.core.graph.Graph"

    def test_is_external_or_stdlib(self):
        assert is_external_or_stdlib("os") is True
        assert is_external_or_stdlib("sys") is True
        assert is_external_or_stdlib("pydantic") is True
        assert is_external_or_stdlib("my_hypothetical_project_module") is False

    def test_stdlib_newer_modules_classified_as_stdlib(self):
        """Stdlib added after Python 3.10 (regression for the fixed hardcoded list).

        These were absent from the old 39-name hardcoded set and relied on the
        fragile find_spec/origin fallback. The canonical sys.stdlib_module_names
        set now covers them unconditionally.
        """
        import sys

        if not hasattr(sys, "stdlib_module_names"):
            pytest.skip("needs Python >= 3.10 (sys.stdlib_module_names)")
        for mod in ("tomllib", "graphlib", "zoneinfo", "contextlib"):
            assert is_external_or_stdlib(mod) is True, mod


class TestGraphSymbolResolver:
    """Tests the resolution behavior of GraphSymbolResolver."""

    def test_import_fqn_match(self, pg):
        """Test resolving an extern node using imports and FQN match."""
        # 1. Create caller file, caller function, and target function
        pg.add_node("caller_file.py", label=NodeLabel.FILE, qualified_name="test_proj.caller_file.py", file_path="caller_file.py")
        pg.add_node("func_a", label=NodeLabel.FUNCTION, qualified_name="test_proj.caller_file.py.func_a", file_path="caller_file.py")

        # Target node that is actually defined in another file
        pg.add_node("target_file.py", label=NodeLabel.FILE, qualified_name="test_proj.target_file.py", file_path="target_file.py")
        pg.add_node("target_func", label=NodeLabel.FUNCTION, qualified_name="test_proj.target_file.py.target_func", file_path="target_file.py")

        # 2. Add IMPORTS edge from caller file to target module
        pg.add_node("target_file", label=NodeLabel.MODULE, qualified_name="test_proj.__import__.target_file", file_path="caller_file.py")
        pg.add_edge(
            source_qname="test_proj.caller_file.py",
            target_qname="test_proj.__import__.target_file",
            type=EdgeType.IMPORTS,
            properties={"text": "from target_file import target_func"}
        )

        # 3. Create __extern__ placeholder node for target_func, called from func_a
        pg.add_node(
            name="target_func",
            label=NodeLabel.FUNCTION,
            qualified_name="test_proj.__extern__.target_func",
            file_path="caller_file.py",
            properties={
                "line": 42,
                "file": "caller_file.py",
                "placeholder": True,
                "caller_node_id": "test_proj.caller_file.py.func_a",
                "line_number": 42,
                "raw_symbol_name": "target_func"
            }
        )

        # 4. Create CALLS edge from func_a to placeholder
        pg.add_edge(
            source_qname="test_proj.caller_file.py.func_a",
            target_qname="test_proj.__extern__.target_func",
            type=EdgeType.CALLS,
            properties={"line": 42}
        )

        # Ensure the unresolved node exists and has an incoming CALLS edge
        assert pg.get_node("test_proj.__extern__.target_func") is not None
        neighbors = pg.get_neighbors("test_proj.__extern__.target_func", direction="incoming")
        assert len(neighbors) == 1

        # 5. Run resolver pass!
        resolved = GraphSymbolResolver.resolve_all(pg)
        assert resolved == 1

        # 6. Verify original __extern__ is deleted
        assert pg.get_node("test_proj.__extern__.target_func") is None

        # 7. Verify edge was redirected directly to target_func
        new_neighbors = pg.get_neighbors("test_proj.target_file.py.target_func", direction="incoming")
        assert len(new_neighbors) == 1
        caller, edge, _ = new_neighbors[0]
        assert caller.qualified_name == "test_proj.caller_file.py.func_a"
        assert edge.properties.get("confidence") == "RESOLVED"
        assert edge.properties.get("confidence_score") == 1.0
        assert edge.properties.get("resolver") == "import"

    def test_unique_global_match(self, pg):
        """Test resolving an extern node using unique global match."""
        pg.add_node("caller_file.py", label=NodeLabel.FILE, qualified_name="test_proj.caller_file.py", file_path="caller_file.py")
        pg.add_node("func_a", label=NodeLabel.FUNCTION, qualified_name="test_proj.caller_file.py.func_a", file_path="caller_file.py")

        # Real symbol exists somewhere with unique name "UniqueServiceClass"
        pg.add_node("unique_file.py", label=NodeLabel.FILE, qualified_name="test_proj.unique_file.py", file_path="unique_file.py")
        pg.add_node("UniqueServiceClass", label=NodeLabel.CLASS, qualified_name="test_proj.unique_file.py.UniqueServiceClass", file_path="unique_file.py")

        # Unresolved extern placeholder node with no import info
        pg.add_node(
            name="UniqueServiceClass",
            label=NodeLabel.FUNCTION,
            qualified_name="test_proj.__extern__.UniqueServiceClass",
            file_path="caller_file.py",
            properties={
                "line": 10,
                "file": "caller_file.py",
                "placeholder": True,
                "caller_node_id": "test_proj.caller_file.py.func_a",
                "line_number": 10,
                "raw_symbol_name": "UniqueServiceClass"
            }
        )
        pg.add_edge(
            source_qname="test_proj.caller_file.py.func_a",
            target_qname="test_proj.__extern__.UniqueServiceClass",
            type=EdgeType.CALLS,
            properties={"line": 10}
        )

        resolved = GraphSymbolResolver.resolve_all(pg)
        assert resolved == 1
        assert pg.get_node("test_proj.__extern__.UniqueServiceClass") is None

        # Verify redirected edge
        new_neighbors = pg.get_neighbors("test_proj.unique_file.py.UniqueServiceClass", direction="incoming")
        assert len(new_neighbors) == 1
        caller, edge, _ = new_neighbors[0]
        assert caller.qualified_name == "test_proj.caller_file.py.func_a"
        assert edge.properties.get("confidence") == "RESOLVED"
        assert edge.properties.get("confidence_score") == 0.85
        assert edge.properties.get("resolver") == "unique_global"

    def test_stdlib_package_match(self, pg):
        """Test resolving an extern node representing stdlib as a Dependency node."""
        pg.add_node("caller_file.py", label=NodeLabel.FILE, qualified_name="test_proj.caller_file.py", file_path="caller_file.py")
        pg.add_node("func_a", label=NodeLabel.FUNCTION, qualified_name="test_proj.caller_file.py.func_a", file_path="caller_file.py")

        # Unresolved stdlib extern "json.dumps"
        pg.add_node(
            name="json.dumps",
            label=NodeLabel.FUNCTION,
            qualified_name="test_proj.__extern__.json.dumps",
            file_path="caller_file.py",
            properties={
                "line": 5,
                "file": "caller_file.py",
                "placeholder": True,
                "caller_node_id": "test_proj.caller_file.py.func_a",
                "line_number": 5,
                "raw_symbol_name": "json.dumps"
            }
        )
        pg.add_edge(
            source_qname="test_proj.caller_file.py.func_a",
            target_qname="test_proj.__extern__.json.dumps",
            type=EdgeType.CALLS,
            properties={"line": 5}
        )

        resolved = GraphSymbolResolver.resolve_all(pg)
        assert resolved == 1
        assert pg.get_node("test_proj.__extern__.json.dumps") is None

        # Verify dependency node exists
        dep_node = pg.get_node("test_proj.dependency.json.dumps")
        assert dep_node is not None
        assert dep_node.label == NodeLabel.DEPENDENCY
        assert dep_node.properties.get("dependency_type") == "stdlib"

        # Verify redirected edge to dependency node
        new_neighbors = pg.get_neighbors("test_proj.dependency.json.dumps", direction="incoming")
        assert len(new_neighbors) == 1
        caller, edge, _ = new_neighbors[0]
        assert caller.qualified_name == "test_proj.caller_file.py.func_a"
        assert edge.properties.get("confidence") == "RESOLVED"
        assert edge.properties.get("confidence_score") == 1.0

    def test_unresolved_fallback(self, pg):
        """Test unresolved placeholder gets fallback confidence and properties."""
        pg.add_node("caller_file.py", label=NodeLabel.FILE, qualified_name="test_proj.caller_file.py", file_path="caller_file.py")
        pg.add_node("func_a", label=NodeLabel.FUNCTION, qualified_name="test_proj.caller_file.py.func_a", file_path="caller_file.py")

        # Dynamic call "getattr_something" (not present globally, not stdlib/import)
        pg.add_node(
            name="getattr_something",
            label=NodeLabel.FUNCTION,
            qualified_name="test_proj.__extern__.getattr_something",
            file_path="caller_file.py",
            properties={
                "line": 20,
                "file": "caller_file.py",
                "placeholder": True,
                "caller_node_id": "test_proj.caller_file.py.func_a",
                "line_number": 20,
                "raw_symbol_name": "getattr_something"
            }
        )
        pg.add_edge(
            source_qname="test_proj.caller_file.py.func_a",
            target_qname="test_proj.__extern__.getattr_something",
            type=EdgeType.CALLS,
            properties={"line": 20}
        )

        resolved = GraphSymbolResolver.resolve_all(pg)
        assert resolved == 0  # not resolved (unresolved fallback)

        # Still exists under original qname but updated properties
        node = pg.get_node("test_proj.__extern__.getattr_something")
        assert node is not None
        assert node.properties.get("unresolved") is True
        assert node.properties.get("confidence") == 0.4
