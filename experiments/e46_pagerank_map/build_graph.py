"""Build a complete PropertyGraph for E46 (no embeddings, no chunk store)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\Project\MSCodeBase")
OUT = Path(__file__).resolve().parent / "results" / "graph_complete.db"
OUT.parent.mkdir(parents=True, exist_ok=True)
if OUT.exists():
    OUT.unlink()

from src.core.graph import PropertyGraph
from src.core.indexing.parser import CodeParser
from src.core.search.graph_adapter import SymbolIndexAdapter

t0 = time.perf_counter()
pg = PropertyGraph(OUT)
si = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
si.index_project(str(ROOT), CodeParser())
pg.count_nodes()
conn = pg._conn
files = conn.execute(
    "SELECT COUNT(DISTINCT file_path) FROM nodes WHERE file_path != ''"
).fetchone()[0]
print(
    f"nodes={pg.count_nodes()} edges={pg.count_edges()} files={files} "
    f"elapsed={time.perf_counter()-t0:.1f}s"
)
