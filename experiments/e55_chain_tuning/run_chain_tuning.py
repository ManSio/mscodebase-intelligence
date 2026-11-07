"""E55: real search-chain modes + cheap flags (no LLM)."""

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
FROZEN = ROOT / "experiments" / "e55_chain_tuning" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e55_chain_tuning" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


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


def make_searcher(**attrs):
    from src.core.search.engine import Searcher

    s = Searcher(FakeIndexer(ROOT), None)
    s._ondemand_rerank = False
    s._multi_reranker_initialized = True
    s._multi_reranker = None
    s._demote_non_code = True
    s._demote_intent_aware = False
    s._ru_synonyms = False
    s._p3_anchor = False
    for k, v in attrs.items():
        setattr(s, k, v)
    return s


async def run_hybrid(qs, **attrs):
    s = make_searcher(**attrs)
    rows, lat = [], []
    for q in qs:
        t0 = time.perf_counter()
        res = await s.hybrid_search_async(q["query"], limit=5)
        lat.append((time.perf_counter() - t0) * 1000)
        rows.append((q, [str((r.get("metadata") or {}).get("file") or "").replace("\\", "/") for r in res]))
    return rows, lat


def run_mode(qs, mode, **attrs):
    s = make_searcher(**attrs)
    rows, lat = [], []
    for q in qs:
        t0 = time.perf_counter()
        out = s.search_with_mode(q["query"], mode=mode, limit=5)
        res = out.get("results", []) if isinstance(out, dict) else []
        lat.append((time.perf_counter() - t0) * 1000)
        rows.append((q, [str((r.get("metadata") or {}).get("file") or "").replace("\\", "/") for r in res]))
    return rows, lat


async def main():
    qs = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    units = [
        ("hybrid", lambda: run_hybrid(qs)),
        ("fast", lambda: run_mode(qs, "fast")),
        ("quality", lambda: run_mode(qs, "quality")),
        ("deep", lambda: run_mode(qs, "deep")),
        ("quality_nodemote", lambda: run_mode(qs, "quality", _demote_non_code=False)),
        ("quality_intent", lambda: run_mode(qs, "quality", _demote_intent_aware=True)),
        ("quality_ru", lambda: run_mode(qs, "quality", _ru_synonyms=True)),
        ("quality_p3", lambda: run_mode(qs, "quality", _p3_anchor=True)),
    ]
    out = {}
    for name, fn in units:
        res = fn()
        rows, lat = await res if asyncio.iscoroutine(res) else res
        item = {
            "hit@1": score(rows, 1),
            "hit@5": score(rows, 5),
            "p50_ms": statistics.median(lat),
            "p95_ms": sorted(lat)[int(len(lat) * 0.95) - 1],
            "subsets": subsets(rows),
            "rows": [{"id": q["id"], "gold": q["gold_file"], "files": files} for q, files in rows],
        }
        out[name] = item
        print(f"{name:<18} h1={item['hit@1']:.3f} h5={item['hit@5']:.3f} "
              f"p50={item['p50_ms']:.0f}ms subsets={item['subsets']}")
    (RESULTS / "e55.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
