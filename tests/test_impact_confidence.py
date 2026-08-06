"""
Tests for impact_analysis confidence scores + depth grouping (Axon pattern, audit.md п.3).

- _call_confidence: 1.0 exact / 0.8 receiver (Class.method) / 0.5 fuzzy (placeholder)
- get_impact_analysis: impact_grouped {depth_1_will_break, depth_2_may_break, depth_3_review}
- ImpactAnalysisTool: impact_grouped виден в ответе
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.graph import EdgeType, NodeLabel, PropertyGraph
from src.core.search.graph_adapter import SymbolIndexAdapter
from src.mcp.tools.search_tools import ImpactAnalysisTool


@pytest.fixture
def pg():
    fd, db_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_path = Path(db_path_str)
    graph = PropertyGraph(db_path)
    yield graph
    graph.close()
    db_path.unlink(missing_ok=True)


def _mk_node(name: str, label=NodeLabel.FUNCTION, props=None):
    m = MagicMock(label=label, properties=props or {})
    m.name = name  # явно: MagicMock(name=...) не отдаёт строку в .name
    return m


# ═══════════════════════════════════════════════════════════════
# _call_confidence
# ═══════════════════════════════════════════════════════════════

class TestCallConfidence:
    def test_exact_resolution_is_1_0(self):
        node = _mk_node("some_func")
        assert SymbolIndexAdapter._call_confidence(node) == 1.0

    def test_qualified_method_is_0_8(self):
        node = _mk_node("ClassName.method_name")
        assert SymbolIndexAdapter._call_confidence(node) == 0.8

    def test_placeholder_is_0_5(self):
        node = _mk_node("ghost", props={"placeholder": True})
        assert SymbolIndexAdapter._call_confidence(node) == 0.5

    def test_placeholder_beats_dotted_name(self):
        node = _mk_node("SomeClass.ghost", props={"placeholder": True})
        assert SymbolIndexAdapter._call_confidence(node) == 0.5


# ═══════════════════════════════════════════════════════════════
# get_impact_analysis — depth grouping + confidence на графе
# ═══════════════════════════════════════════════════════════════

class TestImpactGrouping:
    def _build_graph(self, pg):
        """Граф: e → d → a → b; Class.method → b; ghost(placeholder) → b."""
        for name, label, qname, props in [
            ("b", NodeLabel.FUNCTION, "proj.f.b", {"kind": "function"}),
            ("a", NodeLabel.FUNCTION, "proj.f.a", {"kind": "function"}),
            ("d", NodeLabel.FUNCTION, "proj.f.d", {"kind": "function"}),
            ("e", NodeLabel.FUNCTION, "proj.f.e", {"kind": "function"}),
            ("Class.method", NodeLabel.METHOD, "proj.f.Class.method", {"kind": "method"}),
            ("ghost", NodeLabel.FUNCTION, "proj.__extern__.ghost", {"placeholder": True}),
        ]:
            pg.add_node(name=name, label=label, qualified_name=qname,
                        file_path="f.py", properties=props)

        for src, tgt in [
            ("proj.f.a", "proj.f.b"),
            ("proj.f.Class.method", "proj.f.b"),
            ("proj.__extern__.ghost", "proj.f.b"),
            ("proj.f.d", "proj.f.a"),
            ("proj.f.e", "proj.f.d"),
        ]:
            pg.add_edge(src, tgt, EdgeType.CALLS, properties={"line": 1})

    def test_depth_grouping(self, pg):
        self._build_graph(pg)
        adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)

        res = adapter.get_impact_analysis("b", depth=3)
        grouped = res["impact_grouped"]

        d1 = {c["symbol"] for c in grouped["depth_1_will_break"]}
        assert d1 == {"a", "Class.method", "ghost"}, f"got {d1}"
        assert [c["symbol"] for c in grouped["depth_2_may_break"]] == ["d"]
        assert [c["symbol"] for c in grouped["depth_3_review"]] == ["e"]

    def test_confidence_in_entries(self, pg):
        self._build_graph(pg)
        adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)

        res = adapter.get_impact_analysis("b", depth=3)
        conf = {c["symbol"]: c.get("confidence") for c in res["impact_grouped"]["depth_1_will_break"]}
        assert conf["a"] == 1.0, f"exact должен быть 1.0: {conf}"
        assert conf["Class.method"] == 0.8, f"receiver должен быть 0.8: {conf}"
        assert conf["ghost"] == 0.5, f"placeholder должен быть 0.5: {conf}"

    def test_top_callers_sorted_by_depth_then_confidence(self, pg):
        self._build_graph(pg)
        adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)

        res = adapter.get_impact_analysis("b", depth=3)
        top = res["top_callers"]
        assert top[0]["depth"] == 1
        # в depth 1 первым идёт a (confidence 1.0) перед Class.method (0.8) и ghost (0.5)
        assert top[0]["symbol"] == "a"


# ═══════════════════════════════════════════════════════════════
# ImpactAnalysisTool — impact_grouped в ответе
# ═══════════════════════════════════════════════════════════════

class TestToolSurfacesGrouping:
    async def test_impact_grouped_in_response(self):
        services = MagicMock()
        tool = ImpactAnalysisTool(services)
        tool.require_ready_project = AsyncMock()
        mock_si = MagicMock()
        mock_si.get_impact_analysis.return_value = {
            "call_graph": {"definition": [{"file": "a.py"}]},
            "direct_callers": 3,
            "transitive_callers": 2,
            "direct_callees": 1,
            "transitive_callees": 0,
            "risk_level": "high",
            "risk_score": 60,
            "affected_files": ["a.py", "b.py"],
            "affected_modules": ["src"],
            "impact_grouped": {
                "depth_1_will_break": [{"symbol": "a", "confidence": 1.0}],
                "depth_2_may_break": [],
                "depth_3_review": [],
            },
            "top_callers": [{"symbol": "a", "confidence": 1.0}],
        }
        with patch.object(ImpactAnalysisTool, "resolve_symbol_index", return_value=mock_si):
            res = await tool.execute(symbol="f", depth=2)

        assert isinstance(res, str)
        assert "impact grouped" in res, f"ответ должен содержать impact_grouped:\n{res}"
        assert "depth_1_will_break" in res
