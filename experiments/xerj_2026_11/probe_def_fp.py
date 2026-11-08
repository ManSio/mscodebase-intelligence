"""Precision of `find_definitions` first hit: is it typed as a definition?

Before the filter (measured 2026-11-08): 6 of 60 first hits (10%) were call-site
nodes without `kind` (all in graph_rag.py). After the filter they must be gone.
"""
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)

SAMPLE = 60
FILES = [
    "src/core/indexing/symbol_index.py",
    "src/core/graph_rag.py",
    "src/core/modification_guard.py",
    "src/core/indexing/freshness.py",
    "src/core/indexing/db_manager.py",
    "src/mcp/tools/investigate_tool.py",
    "src/mcp/tools/search_tools.py",
    "src/mcp/server_tools.py",
    "src/core/artifact_paths.py",
    "src/core/eta_predictor.py",
]

services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(ROOT, factory=services.resolve(IndexerFactoryKey))
    sym = indexer._symbol_index

    names: list[str] = []
    for rel in FILES:
        for name in sym.get_symbols_in_file(str(ROOT / rel)) or []:
            if name and name not in names:
                names.append(name)
    names = names[:SAMPLE]
    if not names:
        print("REFUSING: empty sample (T10)")
        raise SystemExit(2)

    kinds = Counter()
    bad = []
    for name in names:
        defs = sym.find_definitions(name) or []
        if not defs:
            kinds["<none>"] += 1
            continue
        kind = str(getattr(defs[0], "kind", "") or "<none>")
        kinds[kind] += 1
        if not kind.endswith("_definition"):
            bad.append((name, kind,
                        str(getattr(defs[0], "file_path", "")).rsplit("/", 1)[-1],
                        getattr(defs[0], "line", 0)))

    total = sum(v for k, v in kinds.items() if k != "<none>")
    good = sum(v for k, v in kinds.items() if k.endswith("_definition"))
    print(f"symbols={len(names)} with_defs={total} typed_definitions={good} "
          f"({good / max(1, total):.3f}) untyped_first={len(bad)}")
    print("first kinds:", dict(kinds.most_common(6)))
    for row in bad[:8]:
        print("   untyped:", row)
finally:
    import asyncio
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
