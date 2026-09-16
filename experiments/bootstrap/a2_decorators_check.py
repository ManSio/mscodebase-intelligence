# -*- coding: utf-8 -*-
"""A2b: почему DECORATES-tool рёбер нет — проверка живых данных."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

con = sqlite3.connect(
    Path.home() / "AppData/Local/mscodebase/projects/bfe9644b/graph.db"
)
deco = con.execute(
    "SELECT COUNT(*) FROM nodes WHERE qualified_name LIKE '%__decorator__%'"
).fetchone()[0]
print("decorator nodes:", deco)
rows = con.execute(
    "SELECT qualified_name FROM nodes WHERE qualified_name LIKE '%__decorator__%' LIMIT 12"
).fetchall()
for r in rows:
    print("  ", r[0])

edges = con.execute(
    "SELECT COUNT(*) FROM edges WHERE type='DECORATES'"
).fetchone()[0]
print("DECORATES edges:", edges)

# узлы-функции, декорированные @@mcp_app.tool: ищем в исходниках
tool = con.execute(
    "SELECT qualified_name FROM nodes WHERE qualified_name LIKE '%mcp_app.tool%' LIMIT 12"
).fetchall()
print("nodes with mcp_app.tool:", len(tool))
for r in tool[:12]:
    print("  ", r[0])