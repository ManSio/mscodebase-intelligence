"""Why does the definition channel come up empty for an external project?"""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)
from src.mcp.tools.investigate_tool import InvestigateTool, _identifiers  # noqa: E402

PROJECT = Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pytest-dev__iniconfig__HEAD-a9e0ad1")

services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(PROJECT, factory=services.resolve(IndexerFactoryKey))
    tool = InvestigateTool(services)
    sym_direct = indexer._symbol_index
    sym_resolved = tool.resolve_symbol_index(str(PROJECT))
    print("same object:", sym_direct is sym_resolved)
    print("counts:", sym_direct.get_symbol_count(), sym_resolved.get_symbol_count())
    for label, sym in (("direct", sym_direct), ("resolved", sym_resolved)):
        defs = sym.find_definitions("ParseError") or []
        print(f"{label}: find_definitions -> {len(defs)}",
              [(getattr(d, 'symbol', '?'), str(getattr(d, 'file_path', '?')).split('iniconfig')[-1])
               for d in defs[:3]])
    print("identifiers:", _identifiers("Where is `ParseError` defined?"))
    out = asyncio.run(tool.execute(query="Where is `ParseError` defined?", limit=8,
                                   project_root=str(PROJECT)))
    print(out[:600])
finally:
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
