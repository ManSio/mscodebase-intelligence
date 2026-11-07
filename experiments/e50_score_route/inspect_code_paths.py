import sys
from pathlib import Path

sys.path.insert(0, r"D:\Project\MSCodeBase")
from src.core.indexing.chunk_store import SQLiteChunkStore, get_chunks_db_path

p = get_chunks_db_path(Path(r"D:\Project\MSCodeBase"))
s = SQLiteChunkStore(p)
rows = s.search("PageRank демоте non code", limit=1000)
code = [
    (r["metadata"]["file"], r["final_score"])
    for r in rows
    if str(r["metadata"]["file"]).startswith(("src/", "tools/"))
]
print("total", len(rows), "code", len(code))
for x in code[:10]:
    print(x)
