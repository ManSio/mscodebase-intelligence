"""Тесты shortest_path с direction (outgoing/incoming/both) — A2 path queries."""

import pytest

from src.core.graph import EdgeType, PropertyGraph


@pytest.fixture
def pg(tmp_path):
    """Граф: A -> B -> C (outgoing), D -> B (входит в B)."""
    graph = PropertyGraph(str(tmp_path / "test.db"))
    for n in ["A", "B", "C", "D"]:
        graph.add_node(name=n, label="Function", qualified_name=n, file_path="app.py")
    graph.add_edge(source_qname="A", target_qname="B", type=EdgeType.CALLS)
    graph.add_edge(source_qname="B", target_qname="C", type=EdgeType.CALLS)
    graph.add_edge(source_qname="D", target_qname="B", type=EdgeType.CALLS)
    yield graph
    graph.close()


def test_outgoing_default_backward_compat(pg):
    path = pg.shortest_path("A", "C")
    assert [n.qualified_name for n, _ in path] == ["A", "B", "C"]
    assert path[1][1].type == EdgeType.CALLS


def test_incoming(pg):
    path = pg.shortest_path("C", "A", direction="incoming")
    assert [n.qualified_name for n, _ in path] == ["C", "B", "A"]


def test_both_reaches_from_leaf(pg):
    # C не имеет исходящих рёбер: outgoing не находит, both — находит
    assert pg.shortest_path("C", "B") == []
    path = pg.shortest_path("C", "B", direction="both")
    assert len(path) >= 2
    assert path[-1][0].qualified_name == "B"


def test_max_depth(pg):
    assert pg.shortest_path("A", "C", max_depth=1) == []
    assert len(pg.shortest_path("A", "C", max_depth=2)) == 3


def test_same_node(pg):
    path = pg.shortest_path("B", "B")
    assert [n.qualified_name for n, _ in path] == ["B"]
