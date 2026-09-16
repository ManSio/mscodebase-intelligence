# -*- coding: utf-8 -*-
"""A2: посмотреть реальные qname в живой graph.db — как выглядят узлы файлов/функций.
Нужно понять формат qualified_name для построения TESTS-рёбер из trace_result.json.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.artifact_paths import get_graph_db_path

sys.stdout.reconfigure(encoding="utf-8")
p = Path(".").resolve()
db = get_graph_db_path(p)
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row


def sample(label_where, limit=6, tail=6):
    rows = con.execute(
        "SELECT name, label, qualified_name, file_path FROM nodes "
        f"WHERE {label_where} LIMIT {limit}"
    ).fetchall()
    total = con.execute(
        f"SELECT COUNT(*) FROM nodes WHERE {label_where}"
    ).fetchone()[0]
    print(f"  [{total}] {label_where}:")
    for r in rows:
        print(f"    label={r['label']} name={r['name']!r} qname={r['qualified_name']!r}")
    later = con.execute(
        "SELECT name, qualified_name FROM nodes "
        f"WHERE {label_where} LIMIT {limit} OFFSET {max(0, total - tail)}"
    ).fetchall()
    print("   …")
    for r in later:
        print(f"    name={r['name']!r} qname={r['qualified_name']!r}")


print(f"DB: {db}")
sample("label='Function'")
print()
sample("label='Method'")
print()
sample("label='Test'")
print()
# поищем узел, соответствующий конкретной функции из trace
con2 = sqlite3.connect(db)
try:
    row = con2.execute(
        "SELECT id, name, label, qualified_name, file_path FROM nodes "
        "WHERE qualified_name LIKE '%action_receipt.py%' LIMIT 8"
    ).fetchall()
    print("references to action_receipt.py nodes:")
    for r in row:
        print(f"    id={r[0]} label={r[2]} name={r[1]!r} qname={r[3]!r} path={r[4]!r}")
except Exception as e:
    print("ERR", e)