"""E45: structured agent search plan (primary + must_include + symbols)."""

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
FROZEN = Path(__file__).resolve().parent / "frozen" / "PLANS.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


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


def boost(res, must, symbols):
    if not must and not symbols:
        return res
    must_l = [m.lower() for m in must]
    sym_l = {s.lower() for s in symbols}
    for r in res:
        meta = r.get("metadata") or {}
        blob = " ".join(
            [
                str(meta.get("symbol_name", "") or ""),
                str(r.get("text_full") or r.get("text") or ""),
            ]
        ).lower()
        score = float(r.get("final_score", 0.0) or 0.0)
        if must_l and any(m in blob for m in must_l):
            score *= 2.0
        if sym_l and str(meta.get("symbol_name", "")).lower() in sym_l:
            score *= 2.0
        r["_plan_score"] = score
    res.sort(key=lambda r: r.get("_plan_score", 0.0), reverse=True)
    return res


async def run_arm(name, mode, plans):
    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    searcher._p3_anchor = False

    async def one(p):
        t0 = time.perf_counter()
        if mode == "baseline":
            res = await searcher.hybrid_search_async(p["query"], limit=5)
        else:
            res = await searcher.hybrid_search_async(
                p["primary"], limit=30, expand=False
            )
            if mode in ("plan_must", "plan_full"):
                res = boost(res, p.get("must_include", []), [])
            if mode in ("plan_symbols", "plan_full"):
                res = boost(res, [], p.get("symbols", []))
            res = res[:5]
        files = [(r.get("metadata") or {}).get("file", "") for r in res]
        return {
            "id": p["id"],
            "query": p["query"],
            "gold": p["gold_file"],
            "files": files,
            "ms": (time.perf_counter() - t0) * 1000,
            "h1": hit_at(files, p["gold_file"], 1),
            "h5": hit_at(files, p["gold_file"], 5),
            "rr": mrr_at(files, p["gold_file"]),
        }

    await one(plans[0])
    rows = [await one(p) for p in plans]
    await searcher.close()

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
    plans = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not plans:
        print("FATAL: empty plan set", file=sys.stderr)
        return 2
    await run_arm("baseline", "baseline", plans)
    await run_arm("plan_primary", "plan_primary", plans)
    await run_arm("plan_must", "plan_must", plans)
    await run_arm("plan_symbols", "plan_symbols", plans)
    await run_arm("plan_full", "plan_full", plans)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
