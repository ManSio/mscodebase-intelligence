"""Clear stale vector tables and rebuild them at the width the server answers.

A table created at 384 is never recreated: the 768-d query raises
`lance error` and hybrid_search_async silently returns BM25 rows. This script
removes the stale store, reindexes, then proves the dense path actually ran by
requiring a non-empty `dense_score` on a probe row.

Run: python experiments/xerj_2026_11/ru_vs_dense/prepare_dense.py
"""

import asyncio
import os
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
os.environ["MSCODEBASE_DENSE_OFF"] = "false"

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

REPOS = {
    "itsdangerous": Path(
        r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11"
        r"\pallets__itsdangerous__HEAD-672971d"
    ),
    "iniconfig": Path(
        r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11"
        r"\pytest-dev__iniconfig__HEAD-a9e0ad1"
    ),
}


def clear_store(project: Path) -> int:
    from src.core.artifact_paths import get_index_dir

    store = Path(get_index_dir(project)).parent
    removed = 0
    for child in sorted(store.rglob("*"), reverse=True):
        if child.is_dir() and "lance" in child.name.lower():
            try:
                shutil.rmtree(child)
                removed += 1
            except OSError as exc:  # noqa: BLE001 - report, do not count
                print(f"  could not remove {child}: {exc}")
    return removed


def main() -> int:
    from src.core.di_container import (
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )
    from src.providers.embedder.remote_embedder import RemoteEmbedder

    for name, project in REPOS.items():
        removed = clear_store(project)
        services = create_service_collection(project)
        try:
            indexer = services.resolve(ProjectIndexerRegistry).get_indexer(
                project, factory=services.resolve(IndexerFactoryKey)
            )
            embedder = services.resolve(RemoteEmbedder)
            with embedder._mode_lock:
                embedder.mode = "llama_cpp"
            print(f"{name}: removed={removed} embedder_dim={embedder.embedding_dim}")
            indexer.index_project(str(project))
            rows = asyncio.run(
                indexer.searcher.hybrid_search_async("signature payload", limit=5)
            ) or []
            dense_scored = [r for r in rows if (r.get("dense_score") or 0) > 0]
            print(
                f"{name}: rows={len(rows)} with_dense_score={len(dense_scored)} "
                f"table={'yes' if getattr(indexer, 'table', None) is not None else 'no'}"
            )
            if not dense_scored:
                print(f"ASSERT FAILED: {name} dense path returned no dense_score")
                return 2
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
