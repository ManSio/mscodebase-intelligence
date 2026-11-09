"""Negative control that can actually fail.

The first version stored `negative_gold_hit: False` as a literal, so it could
never fail (independent review, 2026-11-09). This one asserts a property of the
returned chunks: a query about websocket reconnection must not return any chunk
that mentions websocket or reconnect. If the search invents such a chunk, the
control fails.

Run: python experiments/xerj_2026_11/ru_vs_dense/negative_control.py --arm A
     python experiments/xerj_2026_11/ru_vs_dense/negative_control.py --arm C
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--arm", choices=["A", "C"], default="C")
ARGS = parser.parse_args()
os.environ["MSCODEBASE_DENSE_OFF"] = "false" if ARGS.arm == "C" else "true"

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

PROJECT = Path(
    r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11"
    r"\pallets__itsdangerous__HEAD-672971d"
)
QUERY = "where is websocket reconnect implemented"
RUN_REPO = "itsdangerous"
ABSENT = ("websocket", "reconnect")


def main() -> int:
    from src.core.di_container import (
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )
    from src.providers.embedder.remote_embedder import RemoteEmbedder

    services = create_service_collection(PROJECT)
    try:
        indexer = services.resolve(ProjectIndexerRegistry).get_indexer(
            PROJECT, factory=services.resolve(IndexerFactoryKey)
        )
        embedder = services.resolve(RemoteEmbedder)
        with embedder._mode_lock:
            embedder.mode = "llama_cpp"
        print(f"arm={ARGS.arm} dense_off={os.environ['MSCODEBASE_DENSE_OFF']} "
              f"embedder_dim={embedder.embedding_dim}")
        rows = asyncio.run(
            indexer.searcher.hybrid_search_async(QUERY, limit=10)
        ) or []
        hits = []
        for index, row in enumerate(rows, 1):
            text = str(row.get("text") or "").lower()
            found = [term for term in ABSENT if term in text]
            if found:
                hits.append(
                    ((row.get("metadata") or {}).get("file"), index, found)
                )
        print(f"rows={len(rows)} chunks mentioning {ABSENT}: {hits or 'none'}")
        if hits:
            print("NEGATIVE CONTROL FAILED: search returned a chunk about the absent concept")
            return 1
        print("NEGATIVE CONTROL PASSED")
        return 0
    finally:
        shutdown = getattr(services, "shutdown", None)
        if callable(shutdown):
            try:
                asyncio.run(shutdown())
            except Exception:  # noqa: BLE001 - shutdown must not mask results
                pass


if __name__ == "__main__":
    raise SystemExit(main())
