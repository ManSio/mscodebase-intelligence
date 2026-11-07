import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
p = Path(r"D:\Project\MSCodeBase\.mscodebase\chunks.db")
c = sqlite3.connect(str(p))
rows = c.execute(
    "SELECT CASE WHEN file_path LIKE 'experiments/%' THEN 'experiments' "
    "WHEN file_path LIKE 'src/%' THEN 'src' "
    "WHEN file_path LIKE 'tools/%' THEN 'tools' "
    "WHEN file_path LIKE 'tests/%' THEN 'tests' "
    "WHEN file_path LIKE 'docs/%' THEN 'docs' ELSE 'other' END, COUNT(*) "
    "FROM chunks GROUP BY 1 ORDER BY 2 DESC"
).fetchall()
print(rows)
print("total", c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
