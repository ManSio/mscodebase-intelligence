"""Is the symbol index populated for a freshly indexed external project?"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)

PROJECTS = {
    "ours": ROOT,
    "itsdangerous": Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pallets__itsdangerous__HEAD-672971d"),
    "iniconfig": Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pytest-dev__iniconfig__HEAD-a9e0ad1"),
}

services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    factory = services.resolve(IndexerFactoryKey)
    for name, path in PROJECTS.items():
        indexer = registry.get_indexer(path, factory=factory)
        sym = indexer._symbol_index
        hits = sym.search_symbols("Signer", top_k=3) if name != "iniconfig" else sym.search_symbols("ParseError", top_k=3)
        count = sym.get_symbol_count() if hasattr(sym, "get_symbol_count") else "?"
        print(f"{name:<13} symbols={count} search_hits={len(hits or [])}")
        for h in (hits or [])[:3]:
            print(f"   {getattr(h, 'symbol', '?')} {getattr(h, 'file_path', '?')}:{getattr(h, 'line', '?')} {getattr(h, 'kind', '?')}")
finally:
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        import asyncio
        try:
            asyncio.run(sd())
        except Exception:
            pass
