"""E33: deterministic ranking signals on top of fused retrieval.

Arms: baseline, FTS5 field weights, test/doc demotion, caller prior + exact-name.
No embeddings, no reranker.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("MSCODEBASE_DENSE_OFF", "true")
os.environ.setdefault("MSCODEBASE_SQLITE_CHUNKS", "true")
os.environ.setdefault("MSCODEBASE_ONDEMAND_RERANK", "false")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
FROZEN = Path(__file__).resolve().parent / "frozen" / "QUERIES.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

NON_CODE = ("tests/", "docs/", "experiments/", "fixtures/", "test/")
FTS_WEIGHTS = (1.0, 1.0, 3.0, 1.5, 1.5)


class FakeIndexer:
    def __init__(self, project_path: Path, symbol_index=None):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = symbol_index


def hit_at(files, gold, k):
    return int(any(f == gold or f.endswith(gold) for f in files[:k]))


def mrr_at(files, gold):
    for i, f in enumerate(files, 1):
        if f == gold or f.endswith(gold):
            return 1.0 / i
    return 0.0


def q_tokens(query):
    from src.core.search.code_tokenizer import tokenize_code

    return set(tokenize_code(query, stopwords=False))


def postprocess(res, query, symbol_index, demote=False, prior=False):
    if not (demote or prior):
        return res
    toks = q_tokens(query)
    for r in res:
        meta = r.get("metadata") or {}
        f = str(meta.get("file", "") or "").replace("\\", "/")
        sym = str(meta.get("symbol_name", "") or "")
        score = float(r.get("final_score", 0.0) or 0.0)
        if demote and any(f.startswith(p) for p in NON_CODE):
            score *= 0.3
        if prior:
            if sym:
                try:
                    callers = len(symbol_index.get_callers(sym)) if symbol_index else 0
                except Exception:
                    callers = 0
                score *= 1.0 + 0.1 * math.log1p(callers)
                if sym.lower() in toks:
                    score *= 2.0
            if any(t in f.lower() for t in toks):
                score *= 1.2
        r["_det_score"] = score
    res.sort(key=lambda r: r.get("_det_score", 0.0), reverse=True)
    return res


async def run_arm(name, fts_weights, demote, prior, queries, symbol_index):
    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT, symbol_index=symbol_index), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    if searcher._chunk_store is not None:
        searcher._chunk_store.field_weights = fts_weights

    async def one(q):
        t0 = time.perf_counter()
        res = await searcher.hybrid_search_async(q["query"], limit=30)
        res = postprocess(res, q["query"], symbol_index, demote=demote, prior=prior)
        res = res[:5]
        files = [(r.get("metadata") or {}).get("file", "") for r in res]
        return {
            "id": q["id"],
            "query": q["query"],
            "gold": q["gold_file"],
            "files": files,
            "ms": (time.perf_counter() - t0) * 1000,
            "h1": hit_at(files, q["gold_file"], 1),
            "h5": hit_at(files, q["gold_file"], 5),
            "rr": mrr_at(files, q["gold_file"]),
        }

    await one(queries[0])
    rows = [await one(q) for q in queries]
    await searcher.close()

    lat = sorted(r["ms"] for r in rows)
    summary = {
        "arm": name,
        "fts_weights": fts_weights,
        "demote": demote,
        "prior": prior,
        "n": len(rows),
        "hit1": sum(r["h1"] for r in rows) / len(rows),
        "hit5": sum(r["h5"] for r in rows) / len(rows),
        "mrr": sum(r["rr"] for r in rows) / len(rows),
        "p50_ms": statistics.median(lat),
        "p95_ms": lat[int(len(lat) * 0.95) - 1],
        "mean_ms": sum(lat) / len(lat),
        "rows": rows,
    }
    (RESULTS / f"{name}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"{name:<26} h1={summary['hit1']:.3f} h5={summary['hit5']:.3f} "
        f"mrr={summary['mrr']:.3f} p50={summary['p50_ms']:.0f}ms "
        f"p95={summary['p95_ms']:.0f}ms"
    )
    return summary


async def main():
    queries = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not queries:
        print("FATAL: empty query set", file=sys.stderr)
        return 2

    symbol_index = None
    try:
        from src.core.artifact_paths import get_graph_db_path
        from src.core.graph import PropertyGraph
        from src.core.search.graph_adapter import SymbolIndexAdapter

        pg = PropertyGraph(get_graph_db_path(ROOT))
        symbol_index = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    except Exception as e:
        print(f"[warn] graph unavailable: {e}")

    await run_arm("baseline", None, False, False, queries, symbol_index)
    await run_arm("fts_weights", FTS_WEIGHTS, False, False, queries, symbol_index)
    await run_arm(
        "fts_weights_demote", FTS_WEIGHTS, True, False, queries, symbol_index
    )
    await run_arm(
        "fts_weights_demote_prior", FTS_WEIGHTS, True, True, queries, symbol_index
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
