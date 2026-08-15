"""EXP-PATH: PropertyGraph.shortest_path — корректность + латентность (H-PATH).

Гипотеза: shortest_path (BFS, graph.py:937) работает на живом графе и
медиана <50ms; gap = только отсутствие action="path" в MCP graph_query.
"""
import sys
import time
import statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from src.core.artifact_paths import get_graph_db_path
from src.core.graph import PropertyGraph

ROOT = Path("D:/Project/MSCodeBase")
pg = PropertyGraph(get_graph_db_path(ROOT))
print(f"graph: {pg.count_nodes()} nodes, {pg.count_edges()} edges")

cands = {}
for pat in ("%Indexer%", "%Searcher%", "%CodeParser%", "%GraphQueryTool%"):
    found = pg.find_nodes(name_pattern=pat, limit=5)
    qns = [n.qualified_name for n in found]
    print(f"pattern {pat!r} -> {qns}")
    if qns:
        cands.setdefault(pat.strip("%"), qns)

CP = "D:.D:/Project/MSCodeBase/src/core/indexing/parser.py.CodeParser"
CPM = "D:.D:/Project/MSCodeBase/src/core/indexing/parser.py.CodeParser._build_chunk_metadata"
GQT = "D:.D:/Project/MSCodeBase/src/mcp/tools/graph_tools.py.GraphQueryTool._execute_cypher"
PG = "D:.D:/Project/MSCodeBase/src/core/graph.py.PropertyGraph"

pairs = [
    (CP, CPM, "class->method (DEFINES)"),
    (GQT, PG, "tool->PropertyGraph (CALLS)"),
    (CP, PG, "CodeParser->PropertyGraph (multi-hop)"),
]
for a, b, label in pairs:
    times = []
    path = []
    for _ in range(7):
        t0 = time.perf_counter()
        path = pg.shortest_path(a, b, max_depth=10)
        times.append((time.perf_counter() - t0) * 1000)
    print(f"\n[{label}] shortest_path({a.rsplit('.', 1)[-1]!r} -> {b.rsplit('.', 1)[-1]!r}): {len(path)} hops")
    for node, edge in path[:8]:
        lbl = edge.type if edge else "-"
        print(f"   {node.qualified_name}  -[{lbl}]->")
    print("latency_ms:", [round(t, 2) for t in times])
    print("median_ms:", round(statistics.median(times), 2))
