# -*- coding: utf-8 -*-
"""E17 specificity probe: distribution of test coverage per function.

Reads the PropertyGraph SQLite directly (no MCP) and reports, per Function
node, the number of TESTS edges and the *minimum* coverage among its tests
(coverage = number of functions a single test executes). Small min-coverage
= the function has a specific test. No writes.
"""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

from src.core.artifact_paths import get_graph_db_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

QUERY = """
SELECT f.name,
       f.file_path,
       COUNT(*) AS n_tests,
       MIN(tc.cov) AS min_cov
FROM nodes f
JOIN edges e ON e.target_id = f.id AND e.type = 'TESTS'
JOIN (
    SELECT source_id, COUNT(*) AS cov
    FROM edges WHERE type = 'TESTS' GROUP BY source_id
) tc ON tc.source_id = e.source_id
WHERE f.label = 'Function'
GROUP BY f.id
ORDER BY min_cov ASC, n_tests ASC
"""


def main() -> None:
    db = get_graph_db_path(ROOT)
    print(f"graph db: {db}")
    conn = sqlite3.connect(str(db))
    rows = conn.execute(QUERY).fetchall()

    total = conn.execute(
        "SELECT COUNT(DISTINCT target_id) FROM edges WHERE type='TESTS'"
    ).fetchone()[0]
    print(f"functions with >=1 TESTS edge: {total}")
    print(f"rows returned: {len(rows)}")

    buckets = {"1-5": 0, "6-20": 0, "21-50": 0, "51-150": 0, "151+": 0}
    for _, _, _, min_cov in rows:
        if min_cov <= 5:
            buckets["1-5"] += 1
        elif min_cov <= 20:
            buckets["6-20"] += 1
        elif min_cov <= 50:
            buckets["21-50"] += 1
        elif min_cov <= 150:
            buckets["51-150"] += 1
        else:
            buckets["151+"] += 1
    print("\nmin-coverage buckets:", buckets)

    print("\nTop 40 most-specific functions:")
    for name, fp, n_tests, min_cov in rows[:40]:
        short = fp.replace("D:/Project/MSCodeBase/", "")
        print(f"  min_cov={min_cov:4}  n_tests={n_tests:4}  {name:42} {short}")
    conn.close()


if __name__ == "__main__":
    main()
