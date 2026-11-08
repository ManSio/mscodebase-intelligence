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
    for name in ("Corpus", "corpus", "Signer", "build_call_graph", "corpus_hub_signing_key",
                 "NonexistentXyz", "IndexStatusReporter"):
        print(f"has_symbol({name!r}) = {sym.has_symbol(name)}")
finally:
    import asyncio
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
