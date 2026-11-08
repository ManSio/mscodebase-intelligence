"""E54: explicit agent-supplied intent (docs/code) on clean index."""

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
FROZEN = ROOT / "experiments" / "e54_explicit_intent" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e54_explicit_intent" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
DB = ROOT / "experiments" / "e52_clean_baseline" / "results" / "chunks_clean.db"


class FakeIndexer:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = None


def score(rows, k):
    return sum(
        1 for q, files in rows
        if any(f == q["gold_file"] or f.endswith(q["gold_file"]) for f in files[:k])
    ) / len(rows)


def subsets(rows):
    code = [(q, f) for q, f in rows if not q["gold_file"].startswith("docs/")]
    docs = [(q, f) for q, f in rows if q["gold_file"].startswith("docs/")]
    return {"code": [score(code, 1), score(code, 5)], "docs": [score(docs, 1), score(docs, 5)]}


async def run_arm(explicit: bool, qs):
    os.environ["MSCODEBASE_CHUNKS_DB"] = str(DB)
    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    searcher._demote_intent_aware = explicit
    searcher._p3_anchor = False

    rows, lat = [], []
    for q in qs:
        intent = "docs" if q["gold_file"].startswith("docs/") else "code"
        t0 = time.perf_counter()
        res = await searcher.hybrid_search_async(
            q["query"], limit=5, intent_hint=intent if explicit else "auto"
        )
        files = [
            str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            for r in res
        ]
        lat.append((time.perf_counter() - t0) * 1000)
        rows.append((q, files))
    return rows, lat


async def main():
    qs = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out = {}
    for label, explicit in (("baseline", False), ("explicit", True)):
        rows, lat = await run_arm(explicit, qs)
        res = {
            "hit@1": score(rows, 1),
            "hit@5": score(rows, 5),
            "p50_ms": statistics.median(lat),
            "subsets": subsets(rows),
            "rows": [
                {"id": q["id"], "gold": q["gold_file"], "files": files}
                for q, files in rows
            ],
        }
        out[label] = res
        print(f"[{label}] hit@1={res['hit@1']:.3f} hit@5={res['hit@5']:.3f} "
              f"p50={res['p50_ms']:.0f}ms subsets={res['subsets']}")
    (RESULTS / "e54.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
