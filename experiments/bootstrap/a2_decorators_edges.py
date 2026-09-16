# -*- coding: utf-8 -*-
"""A2b: рёбра от узла __decorator__.mcp_app.tool — есть ли tool-links."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

con = sqlite3.connect(
    Path.home() / "AppData/Local/mscodebase/projects/bfe9644b/graph.db"
)
con.row_factory = sqlite3.Row

# точный namespace-фильтр
deco_nodes = con.execute(
    "SELECT id, qualified_name FROM nodes WHERE qualified_name LIKE '%.__decorator__.%'"
).fetchall()
print(f"real decorator nodes: {len(deco_nodes)}")
for r in deco_nodes:
    print("  ", r["qualified_name"])

# рёбра от каждого декоратор-узла
for r in deco_nodes:
    nid = r["id"]
    edges = con.execute(
        """SELECT s.qualified_name AS src, t.qualified_name AS tgt, e.type
           FROM edges e JOIN nodes s ON e.source_id=s.id JOIN nodes t ON e.target_id=t.id
           WHERE e.source_id=? ORDER BY e.id""",
        (nid,),
    ).fetchall()
    for e in edges:
        print(f"  EDGE {e['src']} --[{e['type']}]--> {e['tgt']}")