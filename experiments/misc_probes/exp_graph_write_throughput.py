"""Experiment: graph write throughput — per-node transaction vs batched.

Hypothesis (from research, 2026-09-25):
  PropertyGraph.add_node/add_edge open ONE SQLite transaction + acquire the
  Windows named mutex PER node/edge (graph.py:526-544, 816-851). For a code
  index of ~14k symbols + edges this serializes the parse workers and makes
  graph building I/O-bound at ~5% CPU with constant ~3 MB/s disk.

  Industry baseline (voidstar.tech): separate transaction per row = 429 rows/s
  vs one transaction + reused statement = 2.457M rows/s (~5700x).

Arms (same session, fresh temp DB each, identical INSERT SQL):
  A: PropertyGraph.add_node() per node          (named mutex + BEGIN/commit + SELECT back)
  B: raw sqlite3, ONE transaction, reused stmt   (the batched fix)
  C: raw sqlite3, per-node transaction, no mutex (isolates transaction cost from mutex)

Negative control: node/edge counts must be equal across arms (no loss/corruption).

Run: <extension-venv-python> experiments/misc_probes/exp_graph_write_throughput.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.graph import PropertyGraph  # noqa: E402

N_NODES = 2000
N_EDGES = 4000

INSERT_NODE = (
    "INSERT INTO nodes (name, label, qualified_name, file_path, properties) "
    "VALUES (?, ?, ?, ?, ?) "
    "ON CONFLICT(qualified_name) DO UPDATE SET "
    "name=excluded.name, label=excluded.label, file_path=excluded.file_path, "
    "properties=excluded.properties"
)
INSERT_EDGE = (
    "INSERT INTO edges (source_id, target_id, type, weight, properties) "
    "VALUES (?, ?, ?, ?, ?) "
    "ON CONFLICT(source_id, target_id, type) DO UPDATE SET "
    "weight=excluded.weight, properties=excluded.properties"
)


def _tmpdb(tag: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=f"graphexp_{tag}_"))
    return d / "graph.db"


def _counts(db: Path) -> tuple[int, int]:
    c = sqlite3.connect(str(db))
    try:
        n = c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        e = c.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return n, e
    finally:
        c.close()


def arm_a() -> tuple[float, int, int]:
    db = _tmpdb("A")
    pg = PropertyGraph(db)
    t0 = time.perf_counter()
    for i in range(N_NODES):
        pg.add_node(name=f"n{i}", label="Function", qualified_name=f"p.f{i}",
                    file_path="f.py", properties={"line": i})
    for i in range(N_EDGES):
        s = i % N_NODES
        t = (i + 1) % N_NODES
        pg.add_edge(source_qname=f"p.f{s}", target_qname=f"p.f{t}", type="CALLS")
    dt = time.perf_counter() - t0
    n, e = _counts(db)
    return dt, n, e


def arm_d() -> tuple[float, int, int]:
    """The actual fix: PropertyGraph.batch() — one tx for all node/edge writes."""
    db = _tmpdb("D")
    pg = PropertyGraph(db)
    t0 = time.perf_counter()
    with pg.batch():
        for i in range(N_NODES):
            pg.add_node(name=f"n{i}", label="Function", qualified_name=f"p.f{i}",
                        file_path="f.py", properties={"line": i})
        for i in range(N_EDGES):
            s = i % N_NODES
            t = (i + 1) % N_NODES
            pg.add_edge(source_qname=f"p.f{s}", target_qname=f"p.f{t}", type="CALLS")
    dt = time.perf_counter() - t0
    n, e = _counts(db)
    return dt, n, e


def _raw_arms(one_transaction: bool) -> tuple[float, int, int]:
    tag = "B" if one_transaction else "C"
    db = _tmpdb(tag)
    pg = PropertyGraph(db)  # schema is created lazily on first connection
    pg.count_nodes()        # force schema init
    del pg
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    t0 = time.perf_counter()
    if one_transaction:
        conn.execute("BEGIN IMMEDIATE")
    for i in range(N_NODES):
        if not one_transaction:
            conn.execute("BEGIN IMMEDIATE")
        conn.execute(INSERT_NODE, (f"n{i}", "Function", f"p.f{i}", "f.py", '{"line": %d}' % i))
        if not one_transaction:
            conn.commit()
    if one_transaction:
        conn.commit()
    # edges: same one-transaction / per-edge policy
    if one_transaction:
        conn.execute("BEGIN IMMEDIATE")
    ids = dict(conn.execute("SELECT qualified_name, id FROM nodes").fetchall())
    for i in range(N_EDGES):
        s = i % N_NODES
        t = (i + 1) % N_NODES
        if not one_transaction:
            conn.execute("BEGIN IMMEDIATE")
        conn.execute(INSERT_EDGE, (ids[f"p.f{s}"], ids[f"p.f{t}"], "CALLS", 1.0, "{}"))
        if not one_transaction:
            conn.commit()
    if one_transaction:
        conn.commit()
    dt = time.perf_counter() - t0
    conn.close()
    n, e = _counts(db)
    return dt, n, e


def main() -> int:
    print(f"N_NODES={N_NODES} N_EDGES={N_EDGES}  (same INSERT SQL, fresh temp DB per arm)")
    results = {}
    for label, fn in (("A per-call PropertyGraph (mutex+txn)", arm_a),
                      ("B raw, ONE transaction+reused", lambda: _raw_arms(True)),
                      ("C raw, per-node transaction", lambda: _raw_arms(False)),
                      ("D PropertyGraph.batch() [the fix]", arm_d)):
        dt, n, e = fn()
        ent = n + e
        results[label] = (dt, n, e)
        print(f"  {label:38s}: {dt:7.2f}s  {ent/max(dt,1e-9):9.0f} entities/s  (nodes={n} edges={e})")

    a_dt = results["A per-call PropertyGraph (mutex+txn)"][0]
    b_dt = results["B raw, ONE transaction+reused"][0]
    d_dt = results["D PropertyGraph.batch() [the fix]"][0]
    print(f"\n  speedup B/A = {a_dt/max(b_dt,1e-9):.1f}x")
    print(f"  speedup D/A (the fix) = {a_dt/max(d_dt,1e-9):.1f}x")
    print(f"  speedup B/C = {results['C raw, per-node transaction'][0]/max(b_dt,1e-9):.1f}x "
          f"(isolates per-row commit cost)")

    # Negative control: identical entity counts (no loss/corruption).
    counts = {(n, e) for (_, n, e) in results.values()}
    ok = len(counts) == 1 and all(n == N_NODES for (n, _) in counts)
    print(f"  negative control counts equal: {ok}  -> {sorted(counts)}")
    print("VERDICT:", "CONFIRMED — per-entity transaction/mutex is the bottleneck"
          if a_dt / max(b_dt, 1e-9) >= 5 else "INCONCLUSIVE")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
