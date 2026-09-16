# -*- coding: utf-8 -*-
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")
from src.core.artifact_paths import get_graph_db_path

con = sqlite3.connect(get_graph_db_path(Path(".").resolve()))
print("labels of nodes with '::'-style test names or tests/ path:")
for r in con.execute(
    """SELECT label, COUNT(*) c FROM nodes
       WHERE name LIKE 'test_%' AND file_path LIKE '%/tests/%'
       GROUP BY label ORDER BY c DESC"""
).fetchall():
    print("  ", r)
print("TEST label count:", con.execute("SELECT COUNT(*) FROM nodes WHERE label='TEST'").fetchone()[0])
print("TESTS edges:", con.execute("SELECT COUNT(*) FROM edges WHERE type='TESTS'").fetchone()[0])
print("sample test names:")
for r in con.execute(
    """SELECT name, label, qualified_name FROM nodes
       WHERE name LIKE 'test_%' AND file_path LIKE '%/tests/%' LIMIT 3"""
).fetchall():
    print("  ", r)