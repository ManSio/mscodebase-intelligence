"""Does the persisted symbol_index.json load, and what is in it?"""
import json
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
    guard = indexer._index_guard
    db_path = Path(getattr(guard, "db_path", "."))
    print("db_path:", db_path)
    for name in ("symbol_index.json", "symbol_index.pkl"):
        p = db_path / name
        print(f"  {name}: exists={p.exists()} size={p.stat().st_size if p.exists() else 0}")
    json_path = db_path / "symbol_index.json"
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        print("keys:", list(data)[:8])
        for key in ("definitions", "references"):
            block = data.get(key) or {}
            print(f"  {key}: {len(block)} symbols")
            sample = next(iter(block.items()), None)
            if sample:
                print("   sample:", sample[0], sample[1][:2])
    ok = guard.load_symbol_index(indexer._symbol_index)
    print("load_symbol_index ->", ok, "defs:", len(indexer._symbol_index._definitions))
finally:
    import asyncio
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
