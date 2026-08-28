"""DoD #3 — Multi-project isolation: graph_query биндится к explicit project_root.

Проверяет, что graph_query.execute(thread=project_root) честно пробрасывает
project_root в resolve_indexer / resolve_symbol_index (и значит — к нужному
проекту, а не к активному MCP-проекту по умолчанию), и что _resolve_pg
предпочитает explicit-граф при его наличии.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.mcp.tools.graph_tools import GraphQueryTool


@pytest.mark.asyncio
async def test_graph_query_threads_explicit_project_root():
    tool = GraphQueryTool.__new__(GraphQueryTool)
    captured = {}

    def fake_indexer(explicit_project_root=None, bypass_cache=False):
        captured["indexer_pr"] = explicit_project_root
        idx = MagicMock()
        idx.project_path = Path("/active/default")
        return idx

    def fake_si(explicit_project_root=None):
        captured["si_pr"] = explicit_project_root
        return MagicMock()

    tool.resolve_indexer = fake_indexer
    tool.resolve_symbol_index = fake_si

    def _run(project_root):
        with patch("src.core.graph_rag.GraphRAGQueryEngine") as GE:
            ge_inst = MagicMock()
            ge_inst.query_impact.return_value = {
                "risk_score": 0, "direct_impact": [], "tests_to_run": [],
            }
            GE.return_value = ge_inst
            return GE

    # explicit project_root -> должен дойти до resolve_* как "/tmp/projB"
    _run("/tmp/projB")
    out = await tool._execute_query("impact", "foo", {}, project_root="/tmp/projB")
    assert out["status"] == "ok"
    assert captured["indexer_pr"] == "/tmp/projB"
    assert captured["si_pr"] == "/tmp/projB"

    # без project_root -> explicit_project_root=None (активный проект сессии)
    captured.clear()
    _run(None)
    await tool._execute_query("impact", "foo", {})
    assert captured["indexer_pr"] is None
    assert captured["si_pr"] is None


@pytest.mark.asyncio
async def test_graph_query_resolve_pg_prefers_explicit_when_exists(tmp_path):
    """_resolve_pg: explicit project_root с существующим графом -> тот граф,
    DI PropertyGraph НЕ дёргается."""
    tool = GraphQueryTool.__new__(GraphQueryTool)
    tool._services = MagicMock()
    tool._services.resolve.side_effect = AssertionError(
        "DI resolve не должен зваться при explicit-пути"
    )

    graph_db = tmp_path / "mscodebase_graph.db"
    graph_db.write_text("x")

    import src.core.artifact_paths as ap
    import src.core.graph as gr

    orig_ap = ap.get_graph_db_path
    orig_gr = gr.PropertyGraph
    ap.get_graph_db_path = lambda p: graph_db
    sentinel = object()
    gr.PropertyGraph = lambda path: sentinel
    try:
        pg = tool._resolve_pg(str(tmp_path))
        assert pg is sentinel
    finally:
        ap.get_graph_db_path = orig_ap
        gr.PropertyGraph = orig_gr
