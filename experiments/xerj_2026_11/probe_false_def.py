"""Where does the false definition `graph_rag.py:93` come from?"""
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
    raw = sym._definitions.get("get_impact_analysis", [])
    print(f"_definitions['get_impact_analysis'] = {len(raw)}")
    for ref in raw[:6]:
        print(f"  {ref.file_path}:{ref.line} kind={ref.kind} is_def={ref.is_definition}")
    refs = [r for r in (sym.find_references("get_impact_analysis") or [])][:5]
    print(f"references sample: {[(r.file_path.rsplit('/',1)[-1], r.line, r.kind) for r in refs]}")
finally:
    import asyncio
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
