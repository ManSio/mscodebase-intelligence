import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\Project\MSCodeBase")
from src.core.indexing.chunk_store import SQLiteChunkStore, get_chunks_db_path

ROOT = Path(r"D:\Project\MSCodeBase")
store = SQLiteChunkStore(get_chunks_db_path(ROOT))
qs = [json.loads(l) for l in (ROOT / "experiments/e30_prod_rerank/frozen/QUERIES.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
e57 = json.load(open(ROOT / "experiments/e57_auto_intent/results/e57.json", encoding="utf-8"))
by_id = {r["id"]: r for r in e57["rows"]}

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
    d = max((x[0] for x in docs), default=0.0)
    c = max((x[0] for x in code), default=0.0)
    docs_sorted = [fp for sc, fp in sorted(docs, reverse=True)]
    rows.append({"id": q["id"], "gold": q["gold_file"], "margin": d - c, "docs": docs_sorted, "code": by_id[q["id"]]["code_only"]})


def is_hit(files, gold, k, base):
    gname = Path(gold).name
    for f in files[:k]:
        if (Path(f).name == gname) if base else (f == gold or f.endswith(gold)):
            return 1
    return 0


def evaluate(thresholds, subset):
    out = []
    for t in thresholds:
        h1 = 0
        h5 = 0
        docs_hit = 0
        code_fp = 0
        docs_n = 0
        for r in subset:
            route_docs = r["margin"] > t
            files = r["docs"] if route_docs else r["code"]
            h1 += is_hit(files, r["gold"], 1, True)
            h5 += is_hit(files, r["gold"], 5, True)
            if r["gold"].startswith("docs/"):
                docs_n += 1
                docs_hit += is_hit(files, r["gold"], 1, True)
            elif route_docs:
                code_fp += 1
        out.append((t, h1 / len(subset), h5 / len(subset), docs_hit, docs_n, code_fp))
    return out


thresholds = [2, 3, 4, 5, 6, 10]
print("all:")
for t, h1, h5, dh, dn, fp in evaluate(thresholds, rows):
    print(f"  t={t}: h1={h1:.3f} h5={h5:.3f} docs={dh}/{dn} code_fp={fp}")

odd = rows[::2]
even = rows[1::2]
best = max(evaluate(thresholds, odd), key=lambda x: x[1])
held = evaluate([best[0]], even)[0]
print(f"held-out: best odd t={best[0]} odd_h1={best[1]:.3f} even_h1={held[1]:.3f}")


