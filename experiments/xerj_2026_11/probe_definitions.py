"""Exact-lookup probe: does find_definitions() return the real definition?"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)

CASES = {
    Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pallets__itsdangerous__HEAD-672971d"):
        ["Signer", "TimestampSigner", "Serializer", "URLSafeSerializer", "BadSignature", "want_bytes"],
    Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pytest-dev__iniconfig__HEAD-a9e0ad1"):
        ["IniConfig", "ParseError", "SectionWrapper"],
}

services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    factory = services.resolve(IndexerFactoryKey)
    for project, names in CASES.items():
        indexer = registry.get_indexer(project, factory=factory)
        sym = indexer._symbol_index
        print(f"=== {project.name}")
        for name in names:
            defs = sym.find_definitions(name) or []
            print(f"  {name}: {len(defs)}")
            for d in defs[:3]:
                fp = str(getattr(d, "file_path", "?"))
                print(f"     {fp.split(project.name)[-1]}:{getattr(d, 'line', '?')} "
                      f"{getattr(d, 'kind', '?')}")
finally:
    import asyncio
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
