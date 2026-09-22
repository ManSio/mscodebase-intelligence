# -*- coding: utf-8 -*-
"""E17 complexity probe: are there complex functions that still have specific tests?

For every Function node with a test of coverage <= max_cov, compute a rough
complexity (LOC, AST nodes, branch nodes) and report the distribution and the
most complex candidates. Informs whether a "hard" panel is feasible.
"""
import sys
import ast
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.core.artifact_paths import get_graph_db_path  # noqa: E402
from e17_extract import read_function_code  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
COVERAGE_SQL = "SELECT source_id, COUNT(*) cov FROM edges WHERE type='TESTS' GROUP BY source_id"
_BRANCH = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.BoolOp, ast.Match)


def main() -> None:
    conn = sqlite3.connect(str(get_graph_db_path(ROOT)))
    rows = conn.execute(
        f"""
        SELECT f.name, f.file_path, COUNT(*) n_tests, MIN(tc.cov) min_cov
        FROM nodes f
        JOIN edges e ON e.target_id = f.id AND e.type = 'TESTS'
        JOIN ({COVERAGE_SQL}) tc ON tc.source_id = e.source_id
        WHERE f.label = 'Function' AND f.file_path LIKE '%/src/%'
        GROUP BY f.id
        HAVING min_cov <= 5
        """
    ).fetchall()
    conn.close()

    cands = []
    for name, fp, n_tests, min_cov in rows:
        if name == "_" or name.startswith("test_"):
            continue
        code = read_function_code(fp, name)
        if not code:
            continue
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        loc = len([ln for ln in code.splitlines() if ln.strip()])
        nodes = sum(1 for _ in ast.walk(tree))
        branches = sum(1 for n in ast.walk(tree) if isinstance(n, _BRANCH))
        cands.append({"name": name, "file": fp, "loc": loc, "nodes": nodes,
                      "branches": branches, "n_tests": n_tests, "min_cov": min_cov})

    buckets = {"loc<=20": 0, "21-40": 0, "41-80": 0, "81+": 0}
    for c in cands:
        loc = c["loc"]
        key = "loc<=20" if loc <= 20 else "21-40" if loc <= 40 else "41-80" if loc <= 80 else "81+"
        buckets[key] += 1
    print(f"candidates with min_cov<=5 and source: {len(cands)}")
    print("LOC buckets:", buckets)

    print("\nmost complex by (branches, loc):")
    for c in sorted(cands, key=lambda c: (-c["branches"], -c["loc"]))[:25]:
        short = c["file"].replace("D:/Project/MSCodeBase/", "")
        print(f"  loc={c['loc']:3} nodes={c['nodes']:4} branches={c['branches']:3} "
              f"min_cov={c['min_cov']} n={c['n_tests']:2} {c['name']:40} {short}")


if __name__ == "__main__":
    main()
