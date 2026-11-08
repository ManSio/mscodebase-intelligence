"""Rank vs recall: does the searcher retrieve the gold file at all for the misses?

Runs `hybrid_search_async` with a wide limit and reports the gold file's rank in
the raw channel results (0 = absent). If it is absent at 40, no ranking change
helps and the query/embedding is the limit.
"""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)

CASES = [
    ("P04", "Где решается, нужно ли переиндексировать файл?", "src/core/indexing/freshness.py"),
    ("P06", "Какая функция возвращает путь прогресса?", "src/core/artifact_paths.py"),
    ("P13", "Где хранится схема `file_hash` / `file_mtime_ns`?", "src/core/indexing/db_manager.py"),
    ("P14", "Какой документ является каноном публичных чисел?", "docs/FACTS.md"),
    ("P15", "Где LSP-инструмент отправляет за ссылками?", "src/mcp/tools/lsp_tools.py"),
    ("P01", "Где определяется `build_call_graph` и что оно возвращает?", "src/core/indexing/symbol_index.py"),
]

services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(ROOT, factory=services.resolve(IndexerFactoryKey))
    searcher = indexer.searcher
    for task_id, query, gold in CASES:
        rows = asyncio.run(searcher.hybrid_search_async(query, limit=40)) or []
        rank = 0
        for i, row in enumerate(rows, 1):
            meta = row.get("metadata") or {}
            path = str(meta.get("file") or row.get("file") or "")
            if path.replace("\\", "/").endswith(gold):
                rank = i
                break
        print(f"{task_id} rows={len(rows)} gold_rank={rank} "
              f"({'absent at 40' if rank == 0 else 'found at ' + str(rank)})")
        if rows:
            top = [(row.get("metadata") or {}).get("file", "?") for row in rows[:3]]
            print(f"     top3={[str(t).rsplit('/', 1)[-1] for t in top]}")
finally:
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
