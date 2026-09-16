# -*- coding: utf-8 -*-
"""A2: есть ли тестовые узлы в живой БД, какие рёбра к ним, как назван Test."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import sqlite3
from src.core.artifact_paths import get_graph_db_path

sys.stdout.reconfigure(encoding="utf-8")
con = sqlite3.connect(get_graph_db_path(Path(".").resolve()))
con.row_factory = sqlite3.Row

print("labels count:")
for r in con.execute("SELECT label, COUNT(*) c FROM nodes GROUP BY label ORDER BY c DESC").fetchall():
    print(f"  {r['label']:20s} {r['c']}")

print("\ntests* files in graph:")
for r in con.execute(
    "SELECT id, name, label, qualified_name FROM nodes WHERE file_path LIKE '%%tests%%' LIMIT 8"
).fetchall():
    print(f"  {r['id']} {r['label']:12s} {r['name']!r} qname={r['qualified_name']!r}")

print("\nTESTS edges:")
for r in con.execute("SELECT * FROM edges WHERE type='TESTS' LIMIT 5").fetchall():
    print(f"  {dict(r)}")

print("\ndistinct edge types:")
for r in con.execute("SELECT type, COUNT(*) c FROM edges GROUP BY type ORDER BY c DESC LIMIT 20").fetchall():
    print(f"  {r['type']:25s} {r['c']}")