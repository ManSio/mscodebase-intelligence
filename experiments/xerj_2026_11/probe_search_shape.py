"""Live shape of one search call: which stage produced the rows."""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import create_service_collection, IndexerFactoryKey, ProjectIndexerRegistry  # noqa: E402

project = ROOT
services = create_service_collection(project)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(project, factory=services.resolve(IndexerFactoryKey))
    searcher = indexer.searcher
    store = getattr(searcher, "_chunk_store", None)
    print("dense_off          :", getattr(searcher, "_dense_off", "?"))
    print("ondemand_rerank    :", getattr(searcher, "_ondemand_rerank", "?"))
    print("chunk_store rows   :", store.count() if store is not None else None)
    for limit in (5, 20):
        rows = asyncio.run(searcher.hybrid_search_async("incremental index unchanged files", limit=limit)) or []
        timing = getattr(searcher, "_last_rerank_timing", {})
        print(f"limit={limit:<3} rows={len(rows):<3} raw_limit={min(max(limit*4,20),50):<3} "
              f"mode={timing.get('mode')} sources={sorted({str(r.get('source')) for r in rows})}")
finally:
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
