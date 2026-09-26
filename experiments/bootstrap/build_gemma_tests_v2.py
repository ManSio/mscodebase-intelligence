# -*- coding: utf-8 -*-
"""Build TESTS edges for gemma_agent with correct src_dir."""
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Project\MSCodeBase")
sys.stdout.reconfigure(encoding="utf-8")

import json

from src.core.artifact_paths import get_graph_db_path
from src.core.bootstrap_tests import build_tests_edges
from src.core.graph import PropertyGraph

project_root = Path("D:/Project/gemma_agent")
trace_file = project_root / "trace_result.json"
graph_path = get_graph_db_path(project_root)

print("=" * 80)
print("Building TESTS edges for gemma_agent (with src_dir=core)")
print("=" * 80)

trace = json.loads(trace_file.read_text(encoding="utf-8"))
graph_db = PropertyGraph(graph_path)

# Try with src_dir=core
src_dir = project_root / "core"
result = build_tests_edges(trace, project_root, graph_db, src_dir=src_dir)

print(f"\nResult: {result.as_dict()}")
print(f"Missing (first 10): {result.missing[:10]}")

graph_db.close()
