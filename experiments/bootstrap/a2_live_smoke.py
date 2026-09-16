# -*- coding: utf-8 -*-
"""A2 live-smoke: build_tests_edges на реальном trace_result.json и живой БД графа."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

from src.core.artifact_paths import get_graph_db_path
from src.core.bootstrap_tests import build_from_trace_file
from src.core.graph import EdgeType, NodeLabel, PropertyGraph

ROOT = Path(".").resolve()
stats = build_from_trace_file(
    trace_path=ROOT / "experiments/bootstrap/trace_result.json",
    project_root=ROOT,
)

print(f"Graph DB: {get_graph_db_path(ROOT)}")
for k, v in stats.as_dict().items():
    print(f"  {k}: {v}")
if stats.missing:
    print(f"  missing sample ({len(stats.missing)}): {stats.missing[:5]}")

pg = PropertyGraph(get_graph_db_path(ROOT))
print(f"  nodes Test: {pg.count_nodes(NodeLabel.TEST)}")
print(f"  edges TESTS: {pg.count_edges(EdgeType.TESTS)}")