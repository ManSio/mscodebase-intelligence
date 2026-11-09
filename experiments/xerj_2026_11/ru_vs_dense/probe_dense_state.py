"""Prove the dense arm will actually run dense, not fall back to BM25."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
os.environ["MSCODEBASE_DENSE_OFF"] = "false"
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

PROJECT = Path(
    r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11"
    r"\pallets__itsdangerous__HEAD-672971d"
)

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey,
    ProjectIndexerRegistry,
    create_service_collection,
)
from src.providers.embedder.remote_embedder import RemoteEmbedder  # noqa: E402

services = create_service_collection(PROJECT)
try:
    indexer = services.resolve(ProjectIndexerRegistry).get_indexer(
        PROJECT, factory=services.resolve(IndexerFactoryKey)
    )
    embedder = services.resolve(RemoteEmbedder)
    with embedder._mode_lock:
        embedder.mode = "llama_cpp"
    searcher = indexer.searcher
    print("embedder dim          :", embedder.embedding_dim)
    print("searcher.embedder same:", getattr(searcher, "embedder", None) is embedder)
    print("searcher.embedder dim :", getattr(searcher.embedder, "embedding_dim", "?"))
    print("table                 :", getattr(indexer, "table", None) is not None)
    table = getattr(indexer, "table", None)
    if table is not None:
        print("table rows            :", table.count_rows())
    queries = json.loads(
        (Path(__file__).parent / "frozen" / "queries.json").read_text(encoding="utf-8")
    )["queries"]["Q01"]["ru"]
    for query in queries:
        rows = asyncio.run(searcher.hybrid_search_async(query, limit=10)) or []
        dense = sum(1 for r in rows if (r.get("dense_score") or 0) > 0)
        files = [str((r.get("metadata") or {}).get("file") or "") for r in rows[:3]]
        print(f"q={query!r:<45} rows={len(rows)} dense={dense} top3={files}")
finally:
    shutdown = getattr(services, "shutdown", None)
    if callable(shutdown):
        try:
            asyncio.run(shutdown())
        except Exception:  # noqa: BLE001 - shutdown must not mask results
            pass
