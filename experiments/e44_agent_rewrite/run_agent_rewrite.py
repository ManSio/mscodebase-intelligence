"""E44: agent-style multi-query rewrites on the E30 panel."""

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

ROOT = Path(__file__).resolve().parent.parent.parent
FROZEN = Path(__file__).resolve().parent / "frozen" / "QUERIES_REWRITTEN.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

import src.core.search.engine as engine  # noqa: E402

_ORIG_EXPAND = engine._expand_query


class FakeIndexer:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = None


def hit_at(files, gold, k):
    return int(any(f == gold or f.endswith(gold) for f in files[:k]))


def mrr_at(files, gold):
    for i, f in enumerate(files, 1):
        if f == gold or f.endswith(gold):
            return 1.0 / i
    return 0.0


async def run_arm(name, mode, items):
    if mode == "baseline":
        engine._expand_query = _ORIG_EXPAND
    elif mode == "keywords":
        engine._expand_query = lambda q, max_expansions=3: [
            next(
                (it["variants"].get("keywords", q) for it in items if it["query"] == q),
                q,
            )
        ]
    elif mode == "identifiers":
        engine._expand_query = lambda q, max_expansions=3: [
            next(
                (it["variants"].get("identifiers", q) for it in items if it["query"] == q),
                q,
            )
        ]
    elif mode == "agent_all":
        engine._expand_query = lambda q, max_expansions=3: next(
            (it["rewrites"] for it in items if it["query"] == q), [q]
        )

    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    searcher._p3_anchor = False

    async def one(it):
        t0 = time.perf_counter()
        res = await searcher.hybrid_search_async(it["query"], limit=5)
        files = [(r.get("metadata") or {}).get("file", "") for r in res]
        return {
            "id": it["id"],
            "query": it["query"],
            "gold": it["gold_file"],
            "files": files,
            "ms": (time.perf_counter() - t0) * 1000,
            "h1": hit_at(files, it["gold_file"], 1),
            "h5": hit_at(files, it["gold_file"], 5),
            "rr": mrr_at(files, it["gold_file"]),
        }

    await one(items[0])
    rows = [await one(it) for it in items]
    await searcher.close()
    engine._expand_query = _ORIG_EXPAND

    lat = sorted(r["ms"] for r in rows)
    summary = {
        "arm": name,
        "mode": mode,
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
    items = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not items:
        print("FATAL: empty query set", file=sys.stderr)
        return 2
    await run_arm("baseline", "baseline", items)
    await run_arm("keywords", "keywords", items)
    await run_arm("identifiers", "identifiers", items)
    await run_arm("agent_all", "agent_all", items)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
