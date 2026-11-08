"""Probe: does the `search` channel of `investigate` return anything at all?

The E1 decomposition showed 0 hits from channel `search` across 24 answers while
symbol/grep/graph/impact delivered 129. Either the searcher returns nothing, or
its rows lose their file/line and get dropped by the merge. Both are silent —
no `degraded` entry — so this script prints the raw rows.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)

QUERIES = [
    "where is build_call_graph defined",
    "Где решается, нужно ли переиндексировать файл?",
    "freshness hash confirm",
    "provenance artifact path outside the project",
]


def main() -> int:
    services = create_service_collection(ROOT)
    try:
        registry = services.resolve(ProjectIndexerRegistry)
        indexer = registry.get_indexer(ROOT, factory=services.resolve(IndexerFactoryKey))
        searcher = indexer.searcher
        for query in QUERIES:
            raw = asyncio.run(searcher.hybrid_search_async(query, limit=8))
            rows = raw or []
            print(f"\n=== {query!r}: {len(rows)} rows")
            for row in rows[:3]:
                keys = sorted(row.keys()) if isinstance(row, dict) else type(row).__name__
                preview = json.dumps(row, ensure_ascii=False, default=str)[:220]
                print(f"  keys={keys}\n    {preview}")
    finally:
        shutdown = getattr(services, "shutdown", None)
        if callable(shutdown):
            try:
                asyncio.run(shutdown())
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
