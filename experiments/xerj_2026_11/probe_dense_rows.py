"""What does the dense searcher return? (row shape + source label)"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["MSCODEBASE_DENSE_OFF"] = "false"

PROJECT = Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pallets__itsdangerous__HEAD-672971d")

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)
from src.providers.embedder.remote_embedder import RemoteEmbedder  # noqa: E402

services = create_service_collection(PROJECT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(PROJECT, factory=services.resolve(IndexerFactoryKey))
    embedder = services.resolve(RemoteEmbedder)
    with embedder._mode_lock:
        embedder.mode = "llama_cpp"
    print("embedder dim:", embedder.embedding_dim)
    rows = asyncio.run(indexer.searcher.hybrid_search_async(
        "Где подпись отделяется от полезной нагрузки?", limit=5)) or []
    print("rows:", len(rows))
    for row in rows[:3]:
        print(" keys:", sorted(row.keys()))
        print(" source:", row.get("source"), "| score:", row.get("final_score"))
        meta = row.get("metadata") or {}
        print(" file:", meta.get("file"), "| keys(meta):", sorted(meta)[:6])
finally:
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
