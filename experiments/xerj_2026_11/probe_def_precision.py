"""E3-lite: how often does find_definitions() return a non-definition?

Samples symbols from the graph, asks the exact lookup, and classifies each hit by
kind. A call site reported as a definition would be promoted by the def-first
channel, so its precision is what the channel's weight must be based on.
"""
import json
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
services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(ROOT, factory=services.resolve(IndexerFactoryKey))
    sym = indexer._symbol_index

    names: list[str] = []
    for _key, refs in list(sym._definitions.items()):
        if refs:
            names.append(refs[0].symbol)
        if len(names) >= SAMPLE:
            break
    names = names[:SAMPLE]
    if not names:
        print("REFUSING: no symbols (T10)")
        raise SystemExit(2)

    kinds = Counter()
    first_kinds = Counter()
    examples = []
    for name in names:
        defs = sym.find_definitions(name) or []
        first = defs[0] if defs else None
        if first is None:
            first_kinds["<none>"] += 1
            continue
        kind = str(getattr(first, "kind", "?"))
        first_kinds[kind] += 1
        for ref in defs:
            kinds[str(getattr(ref, "kind", "?"))] += 1
        if not kind.endswith("_definition"):
            examples.append((name, kind, str(getattr(first, "file_path", "")).rsplit("/", 1)[-1],
                             getattr(first, "line", 0)))

    total_first = sum(first_kinds.values())
    good_first = sum(v for k, v in first_kinds.items() if k.endswith("_definition"))
    print(f"symbols={len(names)} first_hits={total_first} "
          f"first_is_definition={good_first}/{total_first} "
          f"({good_first / max(1, total_first):.3f})")
    print("first kinds:", dict(first_kinds.most_common(8)))
    print("all kinds:", dict(kinds.most_common(8)))
    print("non-definition first hits (sample):")
    for row in examples[:10]:
        print("   ", row)
finally:
    import asyncio
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
