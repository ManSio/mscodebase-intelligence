"""Тесты edge transparency: confidence/evidence на рёбрах (A1)."""

import json

from src.core.graph import EdgeType, PropertyGraph
from src.core.relation_extractor import RelationExtractor
from src.core.search.graph_adapter import SymbolIndexAdapter


def _adapter(tmp_path):
    pg = PropertyGraph(str(tmp_path / "test.db"))
    return pg, SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)


def _find_node(pg, name):
    """Находит узел по суффиксу qualified_name (формат qname зависит от пути)."""
    nodes = pg.find_nodes(name_pattern=f"%.{name}", limit=5)
    assert nodes, f"узел {name!r} не найден"
    return nodes[0]


def test_defines_edge_has_confidence_and_evidence(tmp_path):
    pg, adapter = _adapter(tmp_path)
    adapter._pure_add_definitions(
        "src/core/foo.py",
        [{"name": "bar", "line": 7, "kind": "function_definition"}],
    )
    node = _find_node(pg, "bar")
    edges = pg._get_edges_for_node(node.id, direction="incoming")
    defines = next((e[0] for e in edges if e[0]["type"] == EdgeType.DEFINES), None)
    assert defines is not None
    props = json.loads(defines["properties"])
    assert props["confidence"] == "EXTRACTED"
    assert props["evidence"] == "src/core/foo.py:7"


def test_calls_edge_has_confidence(tmp_path):
    pg, adapter = _adapter(tmp_path)
    adapter._pure_add_definitions(
        "src/core/foo.py",
        [
            {"name": "caller_fn", "line": 1, "kind": "function_definition"},
            {"name": "callee_fn", "line": 5, "kind": "function_definition"},
        ],
    )
    adapter._pure_add_references(
        "src/core/foo.py",
        [{"caller": "caller_fn", "callee": "callee_fn", "line": 2}],
    )
    node = _find_node(pg, "caller_fn")
    out = pg._get_edges_for_node(node.id, direction="outgoing")
    calls = [e[0] for e in out if e[0]["type"] == EdgeType.CALLS]
    assert calls
    props = json.loads(calls[0]["properties"])
    assert props["confidence"] == "EXTRACTED"
    assert props["evidence"] == "src/core/foo.py:2"


def test_assignments_edge_has_confidence(tmp_path):
    pg, adapter = _adapter(tmp_path)
    adapter.add_assignments(
        "src/core/x.py",
        [{"source": "a", "target": "b", "line": 3, "function": "f"}],
    )
    node = _find_node(pg, "a")
    out = pg._get_edges_for_node(node.id, direction="outgoing")
    edge = next((e[0] for e in out if e[0]["type"] == EdgeType.ASSIGNED_FROM), None)
    assert edge is not None
    props = json.loads(edge["properties"])
    assert props["confidence"] == "EXTRACTED"
    assert props["evidence"].endswith("src/core/x.py:3")


class _FakeCommitMemory:
    """Заглушка commit_memory: co-change частота для RelationExtractor."""

    def get_cochange_frequency(self):
        return {"src/a.py|src/b.py": 3}


def test_relation_extractor_cochange_inferred():
    re = RelationExtractor(_FakeCommitMemory())
    rels = re.extract_cochange_relations(min_frequency=1)
    assert rels
    assert rels[0]["type"] == "cochange"
    assert rels[0]["confidence"] == "INFERRED"
