# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import sqlite3

from src.core.artifact_paths import get_graph_db_path

db_path = get_graph_db_path(Path('.'))
conn = sqlite3.connect(str(db_path))

# Проверим TESTS-рёбра
print('=== TESTS edges in graph ===')
result = conn.execute("SELECT COUNT(*) FROM edges WHERE type='TESTS'").fetchone()
print(f'Total TESTS edges: {result[0]}')

# Проверим safe_mkdir
print('\n=== safe_mkdir node ===')
result = conn.execute("SELECT id, name, file_path FROM nodes WHERE name LIKE '%safe_mkdir%' LIMIT 5").fetchall()
for r in result:
    print(f'  id={r[0]}, name={r[1]}, file={r[2]}')

# Проверим TESTS-рёбра для safe_mkdir
if result:
    node_id = result[0][0]
    print(f'\n=== TESTS edges TO safe_mkdir (id={node_id}) ===')
    edges = conn.execute(f"SELECT COUNT(*) FROM edges WHERE type='TESTS' AND target_id={node_id}").fetchone()
    print(f'Incoming TESTS edges: {edges[0]}')

    # Покажем несколько тестов
    tests = conn.execute(f"SELECT source_id FROM edges WHERE type='TESTS' AND target_id={node_id} LIMIT 5").fetchall()
    print('\n=== Sample test nodes ===')
    for t in tests:
        test_node = conn.execute(f"SELECT name, file_path FROM nodes WHERE id={t[0]}").fetchone()
        if test_node:
            print(f'  {test_node[0]} @ {test_node[1]}')

conn.close()
