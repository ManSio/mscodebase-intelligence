"""What distinguishes a graph definition node from a graph call-site node?"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)

symbols = ["get_impact_analysis", "build_call_graph", "ModificationGuard", "find_definitions"]
services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(ROOT, factory=services.resolve(IndexerFactoryKey))
    sym = indexer._symbol_index
    print("adapter:", type(sym).__name__, "mode:", getattr(sym, "_mode", "?"))
    for name in symbols:
        nodes = sym._find_nodes_flexible(name, limit=20) if hasattr(sym, "_find_nodes_flexible") else []
        print(f"\n=== {name}: {len(nodes)} nodes")
        for n in nodes[:5]:
            props = n.properties or {}
            print(f"   {n.label:<10} kind={props.get('kind', '-'):<20} "
                  f"{str(n.file_path).rsplit('/', 1)[-1]}:{props.get('line', '?')}")
finally:
    import asyncio
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
