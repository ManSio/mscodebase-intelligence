"""Paired check: non-code demotion on the SQLite search path (2026-11-09).

Same process, same index, one toggle: `searcher._demote_non_code`. The
treatment is what ships when MSCODEBASE_DEMOTE_NON_CODE=true (the project .env
sets it); before this change the flag only affected the LanceDB branch, so the
default dense_off path returned docs at full score.

Run: python experiments/xerj_2026_11/mcp_audit/eval_sqlite_demote.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8")

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey,
    ProjectIndexerRegistry,
    create_service_collection,
)

ROOT = r"D:\Project\MSCodeBase"
QUESTIONS = [
    ("where is the on-demand rerank resolved", "engine.py"),
    ("where does search_code dispatch by mode", "search_tools.py"),
    ("where is the project state machine", "project_indexer_registry.py"),
    ("how is the knowledge gate K3 checked", "check_knowledge.py"),
    ("where are public claims verified", "verify_public_claims.py"),
    ("where is install sync implemented", "install.py"),
]


def main() -> int:
    services = create_service_collection(Path(ROOT))
    indexer = services.resolve(ProjectIndexerRegistry).get_indexer(
        ROOT, factory=services.resolve(IndexerFactoryKey)
    )
    searcher = indexer.searcher

    for arm in (False, True):
        searcher._demote_non_code = arm
        with searcher._cache_lock:
            searcher._cache.clear()
        docs1 = docs5 = gold1 = gold5 = 0
        print(f"demote={arm}")
        for query, gold in QUESTIONS:
            results = searcher.search_with_mode(query, mode="quality", limit=5)[
                "results"
            ]
            files = [str((r.get("metadata") or {}).get("file", "")) for r in results]
            docs1 += int(bool(files) and files[0].startswith("docs/"))
            docs5 += sum(1 for f in files if f.startswith("docs/"))
            rank = next((i + 1 for i, f in enumerate(files) if gold in f), None)
            gold1 += int(rank == 1)
            gold5 += int(rank is not None and rank <= 5)
            print(f"  rank={rank} {query[:40]:42s} {files[:3]}")
        print(
            f"  docs_top1={docs1}/6 docs_top5={docs5}/30 "
            f"gold_top1={gold1}/6 gold_top5={gold5}/6"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
