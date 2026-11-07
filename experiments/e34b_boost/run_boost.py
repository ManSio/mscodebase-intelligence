"""E34b: stronger deterministic graph/PRF boosts (no models)."""

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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
FROZEN = Path(__file__).resolve().parent / "frozen" / "QUERIES.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


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


def key_of(r):
    meta = r.get("metadata") or {}
    return (
        str(meta.get("file", "") or ""),
        int(meta.get("chunk_index", 0) or 0),
        str(meta.get("symbol_name", "") or ""),
    )


def add(pool, extra, base, factor):
    have = {key_of(r) for r in pool}
    for r in extra:
        if not r:
            continue
        k = key_of(r)
        if k in have:
            continue
        have.add(k)
        r = dict(r)
        r["final_score"] = float(base) * factor
        pool.append(r)


def prf(pool, query, store, factor):
    if not pool:
        return
    meta = pool[0].get("metadata") or {}
    sym = str(meta.get("symbol_name", "") or "")
    if not sym:
        return
    base = float(pool[0].get("final_score", 0.0) or 0.0)
    add(pool, store.search(f"{query} {sym}", limit=10), base, factor)


def graph(pool, symbol_index, store, factor):
    if not pool or symbol_index is None:
        return
    base = float(pool[0].get("final_score", 0.0) or 0.0)
    seen = set()
    for r in pool[:3]:
        sym = str((r.get("metadata") or {}).get("symbol_name", "") or "")
        if not sym or sym in seen:
            continue
        seen.add(sym)
        try:
            g = symbol_index.build_call_graph(sym, depth=1)
        except Exception:
            continue
        refs = (g.get("callers") or []) + (g.get("callees") or [])
        for ref in refs:
            file = str(ref.get("file", "") or "")
            name = str(ref.get("symbol", "") or "")
            if not file or not name:
                continue
            chunk = store.get_symbol_chunk(file, name)
            if chunk:
                add(pool, [chunk], base, factor)


async def run_arm(name, use_prf, use_graph, prf_factor, graph_factor, queries, symbol_index):
    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT, symbol_index=symbol_index), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    store = searcher._chunk_store

    async def one(q):
        t0 = time.perf_counter()
        pool = await searcher.hybrid_search_async(q["query"], limit=30)
        if use_prf and store is not None:
            prf(pool, q["query"], store, prf_factor)
        if use_graph and store is not None:
            graph(pool, symbol_index, store, graph_factor)
        pool.sort(key=lambda r: float(r.get("final_score", 0.0) or 0.0), reverse=True)
        res = pool[:5]
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
        f"{name:<12} h1={summary['hit1']:.3f} h5={summary['hit5']:.3f} "
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

    await run_arm("demote", False, False, 0.8, 0.6, queries, symbol_index)
    await run_arm("graph_x15", False, True, 0.8, 1.5, queries, symbol_index)
    await run_arm("prf_x12", True, False, 1.2, 0.6, queries, symbol_index)
    await run_arm("both_x15", True, True, 1.2, 1.5, queries, symbol_index)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
