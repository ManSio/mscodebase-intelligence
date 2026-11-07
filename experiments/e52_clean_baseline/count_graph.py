import os
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
g = Path(os.environ["LOCALAPPDATA"]) / "mscodebase" / "projects" / "bfe9644b" / "graph.db"
c = sqlite3.connect(str(g))
print("nodes", c.execute("select count(*) from nodes").fetchone()[0])
print("edges", c.execute("select count(*) from edges").fetchone()[0])
print("exp nodes", c.execute("select count(*) from nodes where file_path like 'experiments/%'").fetchone()[0])
print("files", c.execute("select count(distinct file_path) from nodes where file_path != ''").fetchone()[0])
