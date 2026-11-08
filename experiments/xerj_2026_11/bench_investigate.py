"""End-to-end timing of `investigate` in-process (same DI, same tool class).

The MCP host owns the project registry; a separate process sees it as
UNINITIALIZED. This script primes the registry exactly once (the same lazy step
the host does on its first tool call) and then runs the tool. Read-only: it
never acquires the write lock.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey,
    ProjectIndexerRegistry,
    create_service_collection,
)
from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: E402


def main() -> int:
    services = create_service_collection(ROOT)
    try:
        registry = services.resolve(ProjectIndexerRegistry)
        factory = services.resolve(IndexerFactoryKey)
        registry.get_indexer(ROOT, factory=factory)
        tool = InvestigateTool(services)
        for query in ("where is build_call_graph defined", "where is partner_agreement implemented"):
            started = time.perf_counter()
            out = asyncio.run(tool.execute(query=query, limit=8))
            elapsed = time.perf_counter() - started
            head = " | ".join(out.splitlines()[:5])
            print(f"{elapsed:7.2f}s  {query}\n          {head}")
    finally:
        shutdown = getattr(services, "shutdown", None)
        if callable(shutdown):
            try:
                asyncio.run(shutdown())
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
