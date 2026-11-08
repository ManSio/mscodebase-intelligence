"""E36: deterministic pipeline ablation (one stage off per arm)."""

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

import src.core.search.engine as engine  # noqa: E402

_ORIG = {
    "_expand_query": engine._expand_query,
    "apply_bucket_weights": engine.apply_bucket_weights,
    "_boost_exact_name_matches": engine._boost_exact_name_matches,
    "_dedupe_by_symbol": engine._dedupe_by_symbol,
}

ARMS = [
    ("full", set()),
    ("no_expansion", {"expansion"}),
    ("no_bucket", {"bucket"}),
    ("no_cochange", {"cochange"}),
    ("no_p2", {"p2"}),
    ("no_p3", {"p3"}),
    ("no_o1", {"o1"}),
    ("no_exact", {"exact"}),
    ("no_dedupe", {"dedupe"}),
    ("no_graph", {"graph"}),
    ("no_demote", {"demote"}),
    ("minimal", {"expansion", "bucket", "cochange", "p2", "p3", "o1", "exact", "dedupe", "graph"}),
]


class FakeIndexer:
    def __init__(self, project_path: Path, symbol_index=None):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = symbol_index


async def _async_noop(pool, *args, **kwargs):
    return pool


def _sync_noop_pool(pool, *args, **kwargs):
    return pool


def _reset_module():
    for name, fn in _ORIG.items():
        setattr(engine, name, fn)


def _patch(searcher, disabled):
    _reset_module()
    if "expansion" in disabled:
        engine._expand_query = lambda q, max_expansions=3: [q]
    if "bucket" in disabled:
        engine.apply_bucket_weights = lambda chunks, intent_hint="auto": chunks
    if "exact" in disabled:
        engine._boost_exact_name_matches = lambda results, query: results
    if "dedupe" in disabled:
        engine._dedupe_by_symbol = lambda results: results
    if "cochange" in disabled:
        searcher._apply_co_change_boost = lambda chunks: chunks
    if "p2" in disabled:
        searcher._anchor_identifier_chunks_async = _async_noop
    if "p3" in disabled:
        searcher._anchor_module_head_chunks_async = _async_noop
    if "o1" in disabled:
        searcher._apply_o1_identifier_boost = _sync_noop_pool
    if "graph" in disabled:
        searcher._graph_stage = lambda *a, **k: []
    if "demote" in disabled:
        searcher._demote_non_code = False


def hit_at(files, gold, k):
    return int(any(f == gold or f.endswith(gold) for f in files[:k]))


def mrr_at(files, gold):
    for i, f in enumerate(files, 1):
        if f == gold or f.endswith(gold):
            return 1.0 / i
    return 0.0


async def run_arm(name, disabled, queries, symbol_index):
    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT, symbol_index=symbol_index), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    _patch(searcher, disabled)

    async def one(q):
        t0 = time.perf_counter()
        res = await searcher.hybrid_search_async(q["query"], limit=5)
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
    _reset_module()

    lat = sorted(r["ms"] for r in rows)
    summary = {
        "arm": name,
        "disabled": sorted(disabled),
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
        f"{name:<14} h1={summary['hit1']:.3f} h5={summary['hit5']:.3f} "
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

    for name, disabled in ARMS:
        await run_arm(name, disabled, queries, symbol_index)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

