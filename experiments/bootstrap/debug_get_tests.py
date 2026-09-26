# -*- coding: utf-8 -*-
"""Debug get_tests_for_symbol step by step."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.artifact_paths import get_graph_db_path
from src.core.graph import EdgeType, NodeLabel, PropertyGraph
from src.core.search.graph_adapter import SymbolIndexAdapter

ROOT = Path(__file__).resolve().parents[2]
pg = PropertyGraph(get_graph_db_path(ROOT))
adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)

symbol = "safe_mkdir"
file_path = "src/core/artifact_paths.py"

print("=== Debug get_tests_for_symbol ===")
print(f"symbol: {symbol}")
print(f"file_path: {file_path}")

# Step 1: find_nodes
print(f"\n[Step 1] find_nodes(label=FUNCTION, name_pattern=%{symbol}%, file_path={file_path})")
candidates = pg.find_nodes(
    label=NodeLabel.FUNCTION,
    name_pattern=f"%{symbol}%",
    file_path=file_path,
    limit=5,
)
print(f"  Found {len(candidates)} candidates")
for c in candidates:
    print(f"    {c.name} @ {c.file_path} (qname={c.qualified_name})")

# Step 2: Попробуем без file_path
print("\n[Step 2] find_nodes без file_path")
candidates2 = pg.find_nodes(
    label=NodeLabel.FUNCTION,
    name_pattern=f"%{symbol}%",
    limit=5,
)
print(f"  Found {len(candidates2)} candidates")
for c in candidates2:
    print(f"    {c.name} @ {c.file_path}")

# Step 3: Проверим get_neighbors для первого кандидата
if candidates2:
    node = candidates2[0]
    print(f"\n[Step 3] get_neighbors({node.qualified_name}, TESTS, incoming)")
    neighbors = pg.get_neighbors(
        node.qualified_name,
        edge_type=EdgeType.TESTS,
        direction="incoming",
        max_nodes=10,
    )
    print(f"  Found {len(neighbors)} neighbors")
    for n, e, d in neighbors[:5]:
        print(f"    {n.name} @ {n.file_path} (label={n.label})")

pg.close()
