# -*- coding: utf-8 -*-
"""Debug: check how functions are stored in gemma_agent graph."""
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Project\MSCodeBase")
sys.stdout.reconfigure(encoding="utf-8")

from src.core.artifact_paths import get_graph_db_path
from src.core.graph import NodeLabel, PropertyGraph

project_root = Path("D:/Project/gemma_agent")
graph_path = get_graph_db_path(project_root)
graph_db = PropertyGraph(graph_path)

# Check sample function nodes
print("=== Sample Function nodes in graph ===")
funcs = graph_db.find_nodes(label=NodeLabel.FUNCTION, limit=10)
for f in funcs:
    print(f"  name={f.name}, file_path={f.file_path}")

# Check trace paths
print("\n=== Sample trace entries ===")
import json

trace_file = project_root / "trace_result.json"
trace = json.loads(trace_file.read_text(encoding="utf-8"))
for i, (nodeid, entries) in enumerate(trace.items()):
    if i >= 3:
        break
    print(f"  {nodeid}")
    for e in entries[:3]:
        print(f"    {e}")

graph_db.close()
