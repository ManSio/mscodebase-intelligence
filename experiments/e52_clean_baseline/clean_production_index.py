import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
p = r"D:\Project\MSCodeBase\.mscodebase\chunks.db"
c = sqlite3.connect(p)
c.execute("DELETE FROM chunks WHERE file_path LIKE 'experiments/%'")
c.commit()
print("experiments left", c.execute("SELECT COUNT(*) FROM chunks WHERE file_path LIKE 'experiments/%'").fetchone()[0])
print("total", c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
print("fts", c.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0])
