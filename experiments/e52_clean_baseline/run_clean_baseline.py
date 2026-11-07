"""E52: contaminated vs clean-index BM25 and production-like baselines."""

from __future__ import annotations

import asyncio
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
FROZEN = ROOT / "experiments" / "e52_clean_baseline" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e52_clean_baseline" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
CLEAN_DB = RESULTS / "chunks_clean.db"

from src.core.indexing.chunk_store import (  # noqa: E402
    SQLiteChunkStore,
    get_chunks_db_path,
)


class FakeIndexer:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = None


def build_clean_db():
    src_path = get_chunks_db_path(ROOT)
    if CLEAN_DB.exists():
        CLEAN_DB.unlink()
    src = SQLiteChunkStore(src_path)
    dst = SQLiteChunkStore(CLEAN_DB)
    kept, removed = [], 0
    for r in src.all_records():
        fp = str(r.get("file_path") or "").replace("\\", "/")
        if fp.startswith("experiments/") or fp.startswith(".mscodebase/"):
            removed += 1
            continue
        kept.append(r)
    dst.upsert_records(kept)
    return src_path, len(kept), removed


def best_files(results):
    best = {}
    for r in results:
        fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
        if not fp:
            continue
        score = float(r.get("final_score") or 0.0)
        if fp not in best or score > best[fp][0]:
            best[fp] = (score, r)
    return [f for f, _ in sorted(best.items(), key=lambda kv: -kv[1][0])]


async def run_production(db_path: Path, qs):
    os.environ["MSCODEBASE_CHUNKS_DB"] = str(db_path)
    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    searcher._p3_anchor = False

    rows, lat = [], []
    for q in qs:
        t0 = time.perf_counter()
        res = await searcher.hybrid_search_async(q["query"], limit=5)
        files = [
            str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            for r in res
        ]
        lat.append((time.perf_counter() - t0) * 1000)
        rows.append((q, files))
    return rows, lat


def run_bm25(db_path: Path, qs):
    store = SQLiteChunkStore(db_path)
    rows, lat, leakage = [], [], 0
    for q in qs:
        t0 = time.perf_counter()
        res = store.search(q["query"], limit=1000)
        files = best_files(res)
        lat.append((time.perf_counter() - t0) * 1000)
        if any(f.endswith("4A_unit_of_return/frozen/f5/queries.md") for f in files[:100]):
            leakage += 1
        rows.append((q, files))
    return rows, lat, leakage


def score(rows, k):
    return sum(
        1 for q, files in rows
        if any(f == q["gold_file"] or f.endswith(q["gold_file"]) for f in files[:k])
    ) / len(rows)


async def main():
    qs = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    src_path, kept, removed = build_clean_db()
    print(f"source={src_path} kept={kept} removed={removed}")
    out = {"kept": kept, "removed": removed}

    for label, db in (("contaminated", src_path), ("clean", CLEAN_DB)):
        rows, lat, leakage = run_bm25(db, qs)
        bm25 = {"hit@1": score(rows, 1), "hit@5": score(rows, 5),
                "p50_ms": statistics.median(lat), "leakage_queries": leakage}
        prod_rows, prod_lat = await run_production(db, qs)
        prod = {
            "hit@1": score(prod_rows, 1),
            "hit@5": score(prod_rows, 5),
            "p50_ms": statistics.median(prod_lat),
        }
        def subs(sel_rows):
            code = [(q, f) for q, f in sel_rows if not q["gold_file"].startswith("docs/")]
            docs = [(q, f) for q, f in sel_rows if q["gold_file"].startswith("docs/")]
            return {
                "code": [score(code, 1), score(code, 5)],
                "docs": [score(docs, 1), score(docs, 5)],
            }

        out[label] = {
            "bm25": bm25,
            "production": prod,
            "bm25_subsets": subs(rows),
            "production_subsets": subs(prod_rows),
            "rows": [
                {
                    "id": q["id"],
                    "gold": q["gold_file"],
                    "bm25": [
                        int(any(f == q["gold_file"] or f.endswith(q["gold_file"]) for f in bfiles[:1])),
                        int(any(f == q["gold_file"] or f.endswith(q["gold_file"]) for f in bfiles[:5])),
                    ],
                    "production": [
                        int(any(f == q["gold_file"] or f.endswith(q["gold_file"]) for f in pfiles[:1])),
                        int(any(f == q["gold_file"] or f.endswith(q["gold_file"]) for f in pfiles[:5])),
                    ],
                }
                for (q, bfiles), (_, pfiles) in zip(rows, prod_rows)
            ],
        }
        print(f"[{label}] bm25 {bm25}")
        print(f"[{label}] production {prod}")
        print(f"[{label}] subsets {out[label]['bm25_subsets']} / {out[label]['production_subsets']}")

    (RESULTS / "e52.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
