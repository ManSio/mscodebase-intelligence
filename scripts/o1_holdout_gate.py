#!/usr/bin/env python3
"""O1 holdout gate (live, fresh-process): P2 + H1-H12 + N/doc controls.

Usage:
    python scripts/o1_holdout_gate.py [--project D:/Project/MSCodeBase]

Each query runs hybrid_search_async(limit=5) in THIS fresh process
(reranker cache starts empty -> no cache-hit void measurements).
Prints a result table; exit 1 on gate failure (see PASS RULES below).

HARNESS RULE (2026-09-28, verified): all queries run inside ONE event loop
(`asyncio.run(_run_all(...))` once). The old per-query `asyncio.run()` pattern
silently degrades every even-positioned query to reranker passthrough
(provider-None, reranker_ms=0): asyncio primitives (locks/semaphores/client)
bound to the first, now-closed loop misbehave on alternating fresh loops.
A degraded row (reranker_ms falsy) fails loudly instead of judging rank on
passthrough order.

Holdout set note: no canonical H1-H12 exists on main (verified 2026-09-28:
grep finds only unrelated H-labels in diary/archive). H1-H12 below are
O1-holdout-v1, defined HERE (multi-token identifier queries with known
target files, disjoint from the frozen eval-16 calibration use).
"""
import argparse
import asyncio
import sys
import time
import traceback
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — encoding guard must never fail startup
        pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Per-query cap: one hung hybrid_search_async must fail its row, never the gate.
QUERY_TIMEOUT = 120

P2 = {"id": "P2", "query": "hybrid_search_async reciprocal_rank_fusion FTS5 BM25",
      "target": "src/core/search/engine.py", "expect_rank": 1}

HOLDOUT = [
    {"id": "H1", "query": "hybrid_search_async BM25 vector FTS5 ranking",
     "target": "src/core/search/engine.py"},
    {"id": "H2", "query": "BM25 common term index search query ranking",
     "target": None, "expect_no_boost": True},  # collision control
    {"id": "H3", "query": "ArtifactGC 30d projects 90d telemetry retention",
     "target": "src/core/artifact_gc.py"},
    {"id": "H4", "query": "resolve_ubatch embed 512 rerank 1024 batch",
     "target": "src/providers/reranker/llama_install.py"},
    {"id": "H5", "query": "_is_pid_alive OpenProcess SYNCHRONIZE stale PID guard",
     "target": "src/providers/reranker/llama_runner.py"},
    {"id": "H6", "query": "add_node add_edge SQLite transaction per node PropertyGraph",
     "target": "src/core/graph.py"},
    {"id": "H7", "query": "LLAMA_EMBED_MAX_TOKENS truncates 480 e5-small context",
     "target": "src/providers/embedder/remote_embedder.py"},
    {"id": "H8", "query": "json_group_array collect Cypher cypher_sql translation",
     "target": "src/core/search/cypher_sql.py"},
    {"id": "H9", "query": "bootstrap_tests TESTS edges verifying tests far better",
     "target": "src/core/bootstrap_tests.py"},
    {"id": "H10", "query": "to_pandas columns lancedb FreshnessChecker broken dead code",
     "target": "src/core/indexing/freshness.py"},
    {"id": "H11", "query": "CodeParser tree_sitter parse_file AST chunks walk",
     "target": "src/core/indexing/parser.py"},
    {"id": "H12", "query": "_cleanup_old_projects 30d retention_policy ArtifactGC",
     "target": "src/core/artifact_gc.py"},
    {"id": "N1", "query": "quantum computing configuration",
     "target": None, "expect_no_boost": True},  # out-of-domain negative
    {"id": "DOC", "query": "begin_write _write_lock RLock reindex freeze server",
     "target": "src/core/indexing/db_writer.py", "expect_no_doc_boost": True},
]


def build_searcher(project: Path):
    from src.core.di_container import IndexerFactoryKey, create_service_collection

    services = create_service_collection(project)
    factory = services.resolve(IndexerFactoryKey)
    indexer = factory(project)
    return indexer.searcher


def rank_of(results, target):
    for i, r in enumerate(results, 1):
        if (r.get("metadata") or {}).get("file") == target:
            return i
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(ROOT))
    args = ap.parse_args()
    project = Path(args.project)
    try:
        import subprocess  # noqa: PLC0415
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=str(ROOT), capture_output=True,
                             timeout=10).stdout.decode().strip()
    except Exception:  # noqa: BLE001 — git metadata is best-effort diagnostics
        rev = "unknown"
    print(f"O1 holdout gate | rev={rev} | project={project} | fresh process")
    searcher = build_searcher(project)
    rows = asyncio.run(_run_all(searcher))
    print("---")
    fails = []
    p2 = rows[0]
    if p2["rank"] != 1:
        fails.append(f"P2 rank={p2['rank']} (expected 1)")
    for row in rows:
        case = next(c for c in [P2, *HOLDOUT] if c["id"] == row["id"])
        if case.get("expect_no_boost") and row["n_boost"]:
            fails.append(f"{row['id']} unexpectedly boosted")
        if case.get("expect_no_doc_boost") and row["n_doc_boost"]:
            fails.append(f"{row['id']} doc chunk boosted")
        if row["void"]:
            fails.append(f"{row['id']} reranker-cache void (wall<2s, no timing)")
        if row["degraded"]:
            fails.append(f"{row['id']} reranker degraded (reranker_ms=0, passthrough)")
        if row["timed_out"]:
            fails.append(f"{row['id']} query timed out (>{QUERY_TIMEOUT}s)")
    if fails:
        print("GATE FAIL: " + "; ".join(fails))
        return 1
    print("GATE PASS")
    return 0


async def _run_all(searcher):
    """Whole sequence on ONE event loop (see HARNESS RULE above)."""
    # Warm-up (discarded): cold FTS5 to_pandas build exceeds the 2s tier budget
    # on main and would silently drop the FTS tier for the FIRST measured query
    # (known issue, PR52 territory). Warm-up uses a disjoint query -> no
    # reranker-cache contamination (cache key includes the query text).
    await asyncio.wait_for(
        searcher.hybrid_search_async("warmup cold start primer", limit=3),
        timeout=QUERY_TIMEOUT,
    )
    rows = []
    for case in [P2, *HOLDOUT]:
        t0 = time.perf_counter()
        try:
            results = await asyncio.wait_for(
                searcher.hybrid_search_async(case["query"], limit=5),
                timeout=QUERY_TIMEOUT,
            )
            timed_out = False
        except asyncio.TimeoutError:
            results = []
            timed_out = True
        wall = time.perf_counter() - t0
        boosted = [r for r in results if r.get("identifier_boost")]
        doc_boosted = [r for r in boosted
                       if str((r.get("metadata") or {}).get("file", ""))
                       .lower().endswith((".md", ".markdown", ".rst", ".txt", ".ipynb"))]
        rank = rank_of(results, case["target"]) if case.get("target") else None
        timing = dict(getattr(searcher, "_last_rerank_timing", None) or {})
        void = wall < 2.0 and timing == {}
        degraded = not timing.get("reranker_ms")
        rows.append({"id": case["id"], "rank": rank, "target": case.get("target"),
                     "n_boost": len(boosted), "n_doc_boost": len(doc_boosted),
                     "n": len(results), "wall": round(wall, 2),
                     "void": void, "degraded": degraded, "timed_out": timed_out})
        print(f"{case['id']:>3} rank={rank} n={len(results)} target={case.get('target')} "
              f"boost={len(boosted)} doc_boost={len(doc_boosted)} wall={wall:.2f}s "
              f"rerank_ms={timing.get('reranker_ms')} model={timing.get('model')}")
    return rows


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — gate must report, never crash silently
        traceback.print_exc()
        sys.exit(1)
