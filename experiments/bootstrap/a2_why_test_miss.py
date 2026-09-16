# -*- coding: utf-8 -*-
"""A2: почему тестовые узлы матчатся только на 6.2% — какие test-файлы в графе."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import sqlite3
from src.core.artifact_paths import get_graph_db_path

sys.stdout.reconfigure(encoding="utf-8")
con = sqlite3.connect(get_graph_db_path(Path(".").resolve()))
con.row_factory = sqlite3.Row

rows = con.execute(
    """SELECT substr(file_path, INSTR(file_path, 'tests/')) as tf, COUNT(*) c
       FROM nodes WHERE label='Function' AND file_path LIKE '%/tests/%'
       GROUP BY tf ORDER BY c DESC LIMIT 30"""
).fetchall()
tot = sum(r["c"] for r in rows)
print(f"test-function nodes TOTAL: {tot}")
print(f"distinct test files with function nodes: {len(rows)}")
for r in rows:
    print(f"  {r['c']:5d}  {r['tf']}")

print()
files = con.execute(
    """SELECT substr(file_path, INSTR(file_path, 'tests/')) as tf, COUNT(*) c
       FROM nodes WHERE file_path LIKE '%/tests/%' AND label='File'
       GROUP BY tf ORDER BY c DESC LIMIT 30"""
).fetchall()
print(f"test File nodes: {len(files)}")
for r in files:
    print(f"  {r['c']:5d}  {r['tf']}")