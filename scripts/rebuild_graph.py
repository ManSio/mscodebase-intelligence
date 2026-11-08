"""Rebuild the PropertyGraph without triggering a vector reindex.

Why: `MSCODEBASE_DENSE_OFF=true` makes `Indexer.index_project()` return early,
so the graph (and all graph/LSP tools) stays empty even though chunks are fresh.
This script indexes symbols/calls directly into a temp DB and atomically replaces
the production graph. Run it while the MCP server is stopped, or restart after.

Usage:
    python scripts/rebuild_graph.py [project_root]
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from src.core.artifact_paths import get_graph_db_path
    from src.core.graph import PropertyGraph
    from src.core.indexing.parser import CodeParser
    from src.core.search.graph_adapter import SymbolIndexAdapter

    target = get_graph_db_path(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".new")
    if temp.exists():
        temp.unlink()

    t0 = time.perf_counter()
    graph = PropertyGraph(temp)
    adapter = SymbolIndexAdapter(graph, mode=SymbolIndexAdapter.MODE_PURE)
    adapter.index_project(str(ROOT), CodeParser())

    conn_nodes = graph.count_nodes()
    conn_edges = graph.count_edges()
    graph.close()
    print(f"built temp graph: nodes={conn_nodes} edges={conn_edges} "
          f"elapsed={time.perf_counter() - t0:.1f}s")

    try:
        os.replace(temp, target)
    except OSError as exc:
        print(f"WARN: could not replace {target} (server running?): {exc}")
        print(f"temp graph kept at {temp}; stop MCP and rename it manually.")
        return 2

    print(f"replaced {target}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
