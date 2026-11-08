"""Does a fresh process load `_definitions` at all, and does load_symbol_index fix it?"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)

services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(ROOT, factory=services.resolve(IndexerFactoryKey))
    sym = indexer._symbol_index
    print("before: defs keys =", len(getattr(sym, "_definitions", {})),
          "count =", sym.get_symbol_count())

    guard = getattr(indexer, "_index_guard", None)
    print("guard:", type(guard).__name__ if guard else None,
          "has load_symbol_index:", hasattr(guard, "load_symbol_index"))
    if guard is not None and hasattr(guard, "load_symbol_index"):
        guard.load_symbol_index(sym)
        print("after : defs keys =", len(getattr(sym, "_definitions", {})),
              "count =", sym.get_symbol_count())
        refs = sym._definitions.get("get_impact_analysis") or []
        print("get_impact_analysis defs:", [(r.file_path.rsplit('/', 1)[-1], r.line, r.kind) for r in refs[:4]])
finally:
    import asyncio
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
