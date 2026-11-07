import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\Project\MSCodeBase")
from src.core.indexing.chunk_store import SQLiteChunkStore, get_chunks_db_path

ROOT = Path(r"D:\Project\MSCodeBase")
store = SQLiteChunkStore(get_chunks_db_path(ROOT))
qs = [json.loads(l) for l in (ROOT / "experiments/e30_prod_rerank/frozen/QUERIES.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

rows = []
for q in qs:
    res = store.search(q["query"], limit=1000)
    docs = []
    code = []
    for r in res:
        fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
        sc = float(r.get("final_score") or 0.0)
        if fp.startswith("docs/"):
            docs.append((sc, fp))
        elif fp.startswith(("src/", "tools/", "scripts/", "tests/")):
            code.append((sc, fp))
    docs.sort(reverse=True)
    code.sort(reverse=True)
    d = docs[0][0] if docs else 0.0
    c = code[0][0] if code else 0.0
    rows.append((q["id"], q["gold_file"], d, c, docs[0][1] if docs else "", code[0][1] if code else ""))

for label, pred in (("docs", lambda r: r[1].startswith("docs/")), ("code", lambda r: not r[1].startswith("docs/"))):
    sel = [r for r in rows if pred(r)]
    print(label, len(sel))
    for idx, name in ((2, "docs_score"), (3, "code_score")):
        vals = [r[idx] for r in sel]
        print(" ", name, "min", round(min(vals), 2), "med", round(statistics.median(vals), 2), "max", round(max(vals), 2))
    margins = [r[2] - r[3] for r in sel]
    print("  margin min/med/max", round(min(margins), 2), round(statistics.median(margins), 2), round(max(margins), 2))

print("\nper query:")
for r in rows:
    print(r[0], r[1][:50], "d=", round(r[2], 2), "c=", round(r[3], 2), "m=", round(r[2]-r[3], 2))
