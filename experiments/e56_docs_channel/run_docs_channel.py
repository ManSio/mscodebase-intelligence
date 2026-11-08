"""E56: cheap docs-only FTS channel + merge policies (no LLM/router)."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("MSCODEBASE_DENSE_OFF", "true")
os.environ.setdefault("MSCODEBASE_SQLITE_CHUNKS", "true")
os.environ.setdefault("MSCODEBASE_ONDEMAND_RERANK", "false")
os.environ.setdefault("MSCODEBASE_DEMOTE_NON_CODE", "true")
os.environ.setdefault("MSCODEBASE_P3_ANCHOR", "false")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\Project\MSCodeBase")
FROZEN = ROOT / "experiments" / "e56_docs_channel" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e56_docs_channel" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


class FakeIndexer:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = None


def best_files(results):
    best = {}
    for r in results:
        fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
        if not fp:
            continue
        sc = float(r.get("final_score") or 0.0)
        if fp not in best or sc > best[fp][0]:
            best[fp] = (sc, r)
    return [f for f, _ in sorted(best.items(), key=lambda kv: -kv[1][0])]


def score(rows, k):
    return sum(
        1 for q, files in rows
        if any(f == q["gold_file"] or f.endswith(q["gold_file"]) for f in files[:k])
    ) / len(rows)


def subsets(rows):
    code = [(q, f) for q, f in rows if not q["gold_file"].startswith("docs/")]
    docs = [(q, f) for q, f in rows if q["gold_file"].startswith("docs/")]
    return {
        "code": [score(code, 1), score(code, 5)],
        "docs": [score(docs, 1), score(docs, 5)],
    }


def main():
    qs = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    from src.core.indexing.chunk_store import SQLiteChunkStore, get_chunks_db_path
    from src.core.search.engine import Searcher

    store = SQLiteChunkStore(get_chunks_db_path(ROOT))
    searcher = Searcher(FakeIndexer(ROOT), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    searcher._demote_intent_aware = False
    searcher._p3_anchor = False

    rows, lat = [], []
    for q in qs:
        t0 = time.perf_counter()
        code = searcher.search_with_mode(q["query"], mode="quality", limit=5)
        code_files = [
            str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            for r in (code.get("results", []) if isinstance(code, dict) else [])
        ]
        docs_res = store.search(q["query"], limit=1000)
        docs_all = best_files(docs_res)
        docs_files = [f for f in docs_all if f.startswith("docs/")]

        arms = {
            "code_only": code_files,
            "docs_only": docs_files,
            "oracle": (docs_files + code_files) if q["gold_file"].startswith("docs/") else (code_files + docs_files),
            "code4_docs1": code_files[:4] + docs_files[:1],
            "docs1_code4": docs_files[:1] + code_files[:4],
        }
        row = {"id": q["id"], "gold": q["gold_file"]}
        for name, files in arms.items():
            row[name] = files
        rows.append(row)
        lat.append((time.perf_counter() - t0) * 1000)

    out = {}
    for name in ("code_only", "docs_only", "oracle", "code4_docs1", "docs1_code4"):
        files_rows = [(q, r[name]) for q, r in zip(qs, rows)]
        item = {
            "hit@1": score(files_rows, 1),
            "hit@5": score(files_rows, 5),
            "hit@10": score(files_rows, 10),
            "subsets": subsets(files_rows),
        }
        out[name] = item
        print(f"{name:<14} h1={item['hit@1']:.3f} h5={item['hit@5']:.3f} "
              f"h10={item['hit@10']:.3f} subsets={item['subsets']}")

    out["p50_ms"] = statistics.median(lat)
    out["p95_ms"] = sorted(lat)[int(len(lat) * 0.95) - 1]
    out["rows"] = rows
    print(f"p50={out['p50_ms']:.0f}ms p95={out['p95_ms']:.0f}ms")
    (RESULTS / "e56.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
