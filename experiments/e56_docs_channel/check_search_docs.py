import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MSCODEBASE_DENSE_OFF", "true")
os.environ.setdefault("MSCODEBASE_SQLITE_CHUNKS", "true")
os.environ.setdefault("MSCODEBASE_ONDEMAND_RERANK", "false")
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\Project\MSCodeBase")
sys.path.insert(0, str(ROOT))
from src.core.search.engine import Searcher


class FakeIndexer:
    def __init__(self, project_path):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = None


qs = [
    json.loads(line)
    for line in (ROOT / "experiments/e56_docs_channel/frozen/QUERIES.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
s = Searcher(FakeIndexer(ROOT), None)
s._ondemand_rerank = False
s._multi_reranker_initialized = True
s._multi_reranker = None

exact = base = base5 = total = 0
for q in qs:
    if not q["gold_file"].startswith("docs/"):
        continue
    total += 1
    files = [str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
             for r in s.search_docs(q["query"], limit=5)]
    if files and files[0] == q["gold_file"]:
        exact += 1
    if files and Path(files[0]).name == Path(q["gold_file"]).name:
        base += 1
    print(q["id"], "|", q["gold_file"], "->", files[:3])
print(f"docs={total} exact@1={exact}/{total} basename@1={base}/{total} basename@5={base5}/{total}")

