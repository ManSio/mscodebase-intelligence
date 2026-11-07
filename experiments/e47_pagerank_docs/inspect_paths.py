import sys
from pathlib import Path

sys.path.insert(0, r"D:\Project\MSCodeBase")
from src.core.indexing.chunk_store import get_chunks_db_path
import sqlite3

p = get_chunks_db_path(Path(r"D:\Project\MSCodeBase"))
print(p)
c = sqlite3.connect(str(p))
print(c.execute("select count(distinct file_path), count(*) from chunks").fetchone())
print(c.execute("select distinct file_path from chunks where file_path like '%docs%' limit 5").fetchall())
