# -*- coding: utf-8 -*-
"""E17 Multi-project check: which projects have PropertyGraph + TESTS edges."""
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Project\MSCodeBase")
sys.stdout.reconfigure(encoding="utf-8")

import sqlite3

from src.core.artifact_paths import get_graph_db_path

projects = [
    "gemma_agent",
    "codebase-memory-mcp-main",
    "commit-",
    "MSPortfolio",
    "OpenCodeClient",
    "Bot_snow",
    "TorrServer-master",
    "MSCodeBase",
]

print("=" * 80)
print("Multi-project PropertyGraph check")
print("=" * 80)

for proj_name in projects:
    proj_path = Path(f"D:/Project/{proj_name}")
    if not proj_path.exists():
        print(f"\n❌ {proj_name}: not found")
        continue

    try:
        graph_path = get_graph_db_path(proj_path)
        if not graph_path.exists():
            print(f"\n⚠️  {proj_name}: no PropertyGraph (not indexed)")
            continue

        conn = sqlite3.connect(str(graph_path))

        # Count nodes by type
        funcs = conn.execute("SELECT COUNT(*) FROM nodes WHERE label='Function'").fetchone()[0]
        tests = conn.execute("SELECT COUNT(*) FROM nodes WHERE label='Test'").fetchone()[0]
        tests_edges = conn.execute("SELECT COUNT(*) FROM edges WHERE type='TESTS'").fetchone()[0]

        # Language coverage
        py_funcs = conn.execute("SELECT COUNT(*) FROM nodes WHERE label='Function' AND file_path LIKE '%.py'").fetchone()[0]
        ts_funcs = conn.execute("SELECT COUNT(*) FROM nodes WHERE label='Function' AND (file_path LIKE '%.ts' OR file_path LIKE '%.tsx')").fetchone()[0]
        go_funcs = conn.execute("SELECT COUNT(*) FROM nodes WHERE label='Function' AND file_path LIKE '%.go'").fetchone()[0]

        # Functions with TESTS edges
        funcs_with_tests = conn.execute("""
            SELECT COUNT(DISTINCT target_id) 
            FROM edges 
            WHERE type='TESTS'
        """).fetchone()[0]

        conn.close()

        print(f"\n✅ {proj_name}")
        print(f"   Functions: {funcs} (Python: {py_funcs}, TS: {ts_funcs}, Go: {go_funcs})")
        print(f"   Test nodes: {tests}")
        print(f"   TESTS edges: {tests_edges}")
        print(f"   Functions with TESTS: {funcs_with_tests} ({funcs_with_tests/funcs*100:.1f}%)" if funcs > 0 else "   Functions with TESTS: 0")

    except Exception as e:
        print(f"\n❌ {proj_name}: error - {e}")
