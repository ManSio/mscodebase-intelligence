"""Does dense retrieval close the natural-language gap that BM25 cannot?

Context (REPORT.md §9): the searcher returns only `sqlite_fts5`, so a question
without a code identifier has recall 0 up to k=40. The llama.cpp embedder
(embeddinggemma-2, multilingual) is up on 127.0.0.1:8080 for the host; this probe
starts it for a side process, indexes ONE small project densely, and asks the
kind of question BM25 failed on.

Gold files were read from the source (each file contains the words that make the
question answerable: `sep` in signer.py, `expire`/`max_age` in timed.py, ...).
"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

REPOS = {
    "itsdangerous": Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pallets__itsdangerous__HEAD-672971d"),
    "iniconfig": Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pytest-dev__iniconfig__HEAD-a9e0ad1"),
}
QUESTIONS = [
    ("itsdangerous", "How is the signature separated from the payload?", "signer.py"),
    ("itsdangerous", "What rejects a signature that has expired?", "timed.py"),
    ("itsdangerous", "Where is url-safe base64 applied?", "url_safe.py"),
    ("iniconfig", "Where are duplicate sections rejected?", "_parse.py"),
    ("iniconfig", "How is an inline comment stripped from a value?", "__init__.py"),
]


def searcher_for(project: Path, dense: bool):
    from src.core.di_container import (
        IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
    )

    services = create_service_collection(project)
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(project, factory=services.resolve(IndexerFactoryKey))
    return services, indexer


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "dense"
    if mode == "dense":
        os.environ["MSCODEBASE_DENSE_OFF"] = "false"
    else:
        os.environ["MSCODEBASE_DENSE_OFF"] = "true"

    hits = 0
    for name, project in REPOS.items():
        services, indexer = searcher_for(project, mode == "dense")
        try:
            if mode == "dense":
                started = time.perf_counter()
                indexer.index_project(str(project))
                print(f"{name}: indexed densely in {time.perf_counter() - started:.1f}s")
            searcher = indexer.searcher
            for corpus, question, gold in QUESTIONS:
                if corpus != name:
                    continue
                rows = asyncio.run(searcher.hybrid_search_async(question, limit=10)) or []
                rank, sources = 0, set()
                for i, row in enumerate(rows, 1):
                    sources.add(str(row.get("source")))
                    meta = row.get("metadata") or {}
                    path = str(meta.get("file") or row.get("file") or "")
                    if path.endswith(gold) and not rank:
                        rank = i
                hits += bool(rank)
                print(f"  [{mode}] {question[:52]:<52} gold={gold:<14} "
                      f"rank={rank or 'absent':<7} sources={sorted(sources)}")
        finally:
            sd = getattr(services, "shutdown", None)
            if callable(sd):
                try:
                    asyncio.run(sd())
                except Exception:
                    pass
    print(f"\n{mode}: top-10 hits {hits}/{len(QUESTIONS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
