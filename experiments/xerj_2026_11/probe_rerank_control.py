"""Live proof: the default is fast, and a per-call override still reranks.

Run: python experiments/xerj_2026_11/probe_rerank_control.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.pop("MSCODEBASE_ONDEMAND_RERANK", None)

PROJECT = Path(
    r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11"
    r"\pallets__itsdangerous__HEAD-672971d"
)
QUERIES = [
    "signature separated from payload",
    "reject expired signature",
    "strip inline comment",
]


def main() -> int:
    from src.config.settings import get_config
    from src.core.di_container import (
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )
    from src.providers.embedder.remote_embedder import RemoteEmbedder

    print("config default ondemand_rerank:", get_config().search.ondemand_rerank)
    services = create_service_collection(PROJECT)
    try:
        indexer = services.resolve(ProjectIndexerRegistry).get_indexer(
            PROJECT, factory=services.resolve(IndexerFactoryKey)
        )
        embedder = services.resolve(RemoteEmbedder)
        with embedder._mode_lock:
            embedder.mode = "llama_cpp"
        searcher = indexer.searcher
        print("searcher._ondemand_rerank:", searcher._ondemand_rerank)
        for rerank in (None, True):
            label = "default" if rerank is None else "rerank=True"
            for query in QUERIES:
                started = time.perf_counter()
                rows = asyncio.run(
                    searcher.hybrid_search_async(query, limit=10, rerank=rerank)
                ) or []
                elapsed = (time.perf_counter() - started) * 1000
                dense = sum(1 for r in rows if (r.get("dense_score") or 0) > 0)
                print(
                    f"{label:<12} {elapsed:8.1f} ms rows={len(rows)} "
                    f"dense={dense} q={query!r}"
                )
        print("after calls, searcher._ondemand_rerank:", searcher._ondemand_rerank)
    finally:
        shutdown = getattr(services, "shutdown", None)
        if callable(shutdown):
            try:
                asyncio.run(shutdown())
            except Exception:  # noqa: BLE001 - shutdown must not mask results
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
