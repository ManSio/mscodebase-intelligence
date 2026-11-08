"""Build the exact-definition item by hand and push it through _merge."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)
from src.mcp.tools.investigate_tool import _merge, _relpath  # noqa: E402

PROJECT = Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pytest-dev__iniconfig__HEAD-a9e0ad1")

services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(PROJECT, factory=services.resolve(IndexerFactoryKey))
    sym = indexer._symbol_index
    ref = sym.find_definitions("ParseError")[0]
    print("attrs:", {k: getattr(ref, k, "<none>") for k in
                     ("symbol", "name", "file_path", "file", "line", "kind")})
    item = {
        "file": getattr(ref, "file_path", "") or getattr(ref, "file", ""),
        "line": int(getattr(ref, "line", 0) or 0),
        "text": f"{getattr(ref, 'symbol', '')} — {getattr(ref, 'kind', 'symbol')}",
        "score": 0.0,
        "weight": 2.5,
        "defines": True,
        "channels": {"definition"},
    }
    root = Path(indexer.project_path).resolve()
    print("item:", item)
    print("relpath:", _relpath(item["file"], root))
    merged = _merge([item], 8, root, False)
    print("merged:", merged)
finally:
    import asyncio
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
