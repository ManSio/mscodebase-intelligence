"""E37: line-granularity chunking simulation on the E30 48-query panel."""

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
FROZEN = Path(__file__).resolve().parent / "frozen" / "QUERIES.jsonl"
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


def build_split_store(lines_per_chunk: int) -> Path:
    from src.core.indexing.chunk_store import SQLiteChunkStore, get_chunks_db_path

    src = SQLiteChunkStore(get_chunks_db_path(ROOT))
    records = src.all_records()
    src.close()

    out = RESULTS / f"chunks_split{lines_per_chunk}.db"
    if out.exists():
        out.unlink()
    store = SQLiteChunkStore(out)
    split_rows = []
    for rec in records:
        text = rec.get("text") or ""
        lines = text.splitlines()
        if len(lines) <= lines_per_chunk:
            split_rows.append(rec)
            continue
        step = max(1, int(lines_per_chunk * 0.75))
        for start in range(0, len(lines), step):
            piece = lines[start : start + lines_per_chunk]
            if len(piece) < 3 and start > 0:
                break
            row = dict(rec)
            row["chunk_id"] = f"{rec['chunk_id']}:split{start}"
            row["chunk_index"] = int(rec.get("chunk_index", 0)) * 1000 + start
            row["text"] = "\n".join(piece)
            row["text_full"] = row["text"]
            row["start_line"] = int(rec.get("start_line", 0) or 0) + start
            row["end_line"] = row["start_line"] + len(piece) - 1
            split_rows.append(row)
    store.upsert_records(split_rows)
    store.close()
    print(f"[split{lines_per_chunk}] rows={len(split_rows)} -> {out}")
    return out


async def run_arm(name: str, db_path: Path | None, queries):
    if db_path is None:
        os.environ.pop("MSCODEBASE_CHUNKS_DB", None)
    else:
        os.environ["MSCODEBASE_CHUNKS_DB"] = str(db_path)

    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    searcher._p3_anchor = False

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
        f"{name:<10} h1={summary['hit1']:.3f} h5={summary['hit5']:.3f} "
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

    await run_arm("current", None, queries)
    for n in (32, 64, 128):
        os.environ.pop("MSCODEBASE_CHUNKS_DB", None)
        db = build_split_store(n)
        await run_arm(f"split{n}", db, queries)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

