"""E31: BGE-M3 cross-encoder rerank over fused lexical/graph candidates.

No vectors are stored. Candidate pool comes from SQLite FTS5 + BM25 + graph;
BGE-M3 reorders the top-N candidates.
"""

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

import httpx  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
FROZEN = Path(__file__).resolve().parent / "frozen" / "QUERIES.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
RERANK_URL = "http://127.0.0.1:8081/rerank"


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


async def run_config(name, pool, rerank, queries, symbol_index, client):
    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT, symbol_index=symbol_index), None)
    searcher._ondemand_rerank = False
    # Clean fused retrieval: do not fall into the multi-provider BGE path.
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None

    async def one(q):
        t0 = time.perf_counter()
        res = await searcher.hybrid_search_async(q["query"], limit=pool)
        files = [(r.get("metadata") or {}).get("file", "") for r in res]
        if rerank and res:
            texts = []
            for r in res:
                t = r.get("text_full") or r.get("text") or ""
                texts.append(str(t)[:2000])
            try:
                rr = client.post(
                    RERANK_URL,
                    json={"query": q["query"], "texts": texts},
                    timeout=120.0,
                )
                rr.raise_for_status()
                scored = rr.json()
                # Response: [{"index": i, "score": s}, ...]
                scored = sorted(scored, key=lambda x: x.get("score", -1e9), reverse=True)
                files = [files[s["index"]] for s in scored if s["index"] < len(files)]
            except Exception as e:
                return {
                    "id": q["id"],
                    "query": q["query"],
                    "gold": q["gold_file"],
                    "files": files[:5],
                    "ms": (time.perf_counter() - t0) * 1000,
                    "h1": hit_at(files, q["gold_file"], 1),
                    "h5": hit_at(files, q["gold_file"], 5),
                    "rr": mrr_at(files, q["gold_file"]),
                    "error": f"rerank: {e}"[:240],
                }
        return {
            "id": q["id"],
            "query": q["query"],
            "gold": q["gold_file"],
            "files": files[:5],
            "ms": (time.perf_counter() - t0) * 1000,
            "h1": hit_at(files, q["gold_file"], 1),
            "h5": hit_at(files, q["gold_file"], 5),
            "rr": mrr_at(files, q["gold_file"]),
            "error": None,
        }

    # Warm-up (loads BM25/FTS5; not counted).
    try:
        await one(queries[0])
    except Exception as e:
        print(f"[warn] warmup {name}: {e}")

    rows = []
    for q in queries:
        rows.append(await one(q))

    await searcher.close()
    lat = sorted(r["ms"] for r in rows)
    summary = {
        "config": name,
        "pool": pool,
        "rerank": rerank,
        "n": len(rows),
        "hit1": sum(r["h1"] for r in rows) / len(rows),
        "hit5": sum(r["h5"] for r in rows) / len(rows),
        "mrr": sum(r["rr"] for r in rows) / len(rows),
        "p50_ms": statistics.median(lat),
        "p95_ms": lat[int(len(lat) * 0.95) - 1],
        "mean_ms": sum(lat) / len(lat),
        "errors": sum(1 for r in rows if r["error"]),
        "rows": rows,
    }
    (RESULTS / f"{name}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"{name:<12} h1={summary['hit1']:.3f} h5={summary['hit5']:.3f} "
        f"mrr={summary['mrr']:.3f} p50={summary['p50_ms']:.0f}ms "
        f"p95={summary['p95_ms']:.0f}ms err={summary['errors']}"
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

    client = httpx.Client(timeout=120.0)
    try:
        await run_config("no_rerank", 5, False, queries, symbol_index, client)
        await run_config("bge_top10", 10, True, queries, symbol_index, client)
        await run_config("bge_top30", 30, True, queries, symbol_index, client)
        await run_config("bge_top50", 50, True, queries, symbol_index, client)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
