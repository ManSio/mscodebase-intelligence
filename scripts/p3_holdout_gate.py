#!/usr/bin/env python3
"""P3 module-head-anchor holdout gate (live, fresh-process): P3 + R2 + H1-H12.

Usage:
    python scripts/p3_holdout_gate.py [--project D:/Project/MSCodeBase]

Pattern follows scripts/p2_holdout_gate.py (ONE event loop, blocking FTS
prebuild, discarded warm-up, explicit reranker-cache clear per case, void /
degraded flags). Case table imported from o1_holdout_gate (O1-holdout-v1,
single source of truth); P3/R2 defined HERE (holdout-style queries with known
target file, disjoint from the frozen eval-16 — NEVER validate on eval-16).

Prereg: experiments/reranker_p3/PREREG.md (2026-09-29). Rerank evidence:
experiments/reranker_p3/rerank_probe_run{1,2}.json + EXPERIMENTS_LOG.md:2809.

PASS RULES: P3 rank==1 (prereg-expected hit: the anchored head chunk scores
highest at the reranker); P2 rank==1 (no regression of the P2 anchor);
expect_no_boost cases unboosted; doc chunks never boosted; no reranker-cache
void measurements; no degraded rows (reranker_ms falsy = invalid, loud fail).
H1-H12 rows are reported in full (falsification clause ii) — gate-relevant
only via the shared controls; any H-row regression vs the p2-gate baseline
is investigated, not silently kept.
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

from scripts.o1_holdout_gate import (  # noqa: E402 — imported for the case table
    HOLDOUT,
    P2,
    QUERY_TIMEOUT,
    build_searcher,
    rank_of,
)

P3 = {"id": "P3", "query": "ArtifactGC _cleanup_old_projects 30d 90d 7d retention_policy",
      "target": "src/core/artifact_gc.py", "expect_rank": 1}

R2 = {"id": "R2", "query": "ArtifactGC 30d projects 90d telemetry 7d logs retention",
      "target": "src/core/artifact_gc.py", "expect_rank": 1}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(ROOT))
    args = ap.parse_args()
    project = Path(args.project)
    try:
        import subprocess  # noqa: PLC0415

        rev = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(ROOT),
                capture_output=True,
                timeout=10,
            )
            .stdout.decode()
            .strip()
        )
    except Exception:  # noqa: BLE001 — git metadata is best-effort diagnostics
        rev = "unknown"
    print(f"P3-anchor holdout gate | rev={rev} | project={project} | fresh process")
    searcher = build_searcher(project)
    rows = asyncio.run(_run_all(searcher))
    print("---")
    fails = []
    for must in (P2, P3, R2):
        row = next(r for r in rows if r["id"] == must["id"])
        if row["rank"] != 1:
            fails.append(f"{must['id']} rank={row['rank']} (expected 1)")
    for row in rows:
        case = next(c for c in [P2, P3, R2, *HOLDOUT] if c["id"] == row["id"])
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
    """Whole sequence on ONE event loop (see p2_holdout_gate HARNESS LESSON)."""
    # Blocking FTS prebuild (discarded): cold build ~2.9s > 2s tier budget.
    t0 = time.perf_counter()
    await asyncio.to_thread(searcher._build_fts5_index)
    print(f"FTS prebuild (discarded): {time.perf_counter() - t0:.2f}s")
    # Discarded warm-up on a disjoint query (cache key includes query text).
    await asyncio.wait_for(
        searcher.hybrid_search_async("warmup cold start primer", limit=3),
        timeout=QUERY_TIMEOUT,
    )
    rows = []
    for case in [P2, P3, R2, *HOLDOUT]:
        searcher._reranker_cache.clear()
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
        doc_boosted = [
            r
            for r in boosted
            if str((r.get("metadata") or {}).get("file", ""))
            .lower()
            .endswith((".md", ".markdown", ".rst", ".txt", ".ipynb"))
        ]
        rank = rank_of(results, case["target"]) if case.get("target") else None
        timing = dict(getattr(searcher, "_last_rerank_timing", None) or {})
        void = wall < 2.0 and timing == {}
        degraded = not timing.get("reranker_ms")
        rows.append(
            {
                "id": case["id"],
                "rank": rank,
                "target": case.get("target"),
                "n_boost": len(boosted),
                "n_doc_boost": len(doc_boosted),
                "n": len(results),
                "wall": round(wall, 2),
                "void": void,
                "degraded": degraded,
                "timed_out": timed_out,
            }
        )
        print(
            f"{case['id']:>3} rank={rank} n={len(results)} target={case.get('target')} "
            f"boost={len(boosted)} doc_boost={len(doc_boosted)} wall={wall:.2f}s "
            f"rerank_ms={timing.get('reranker_ms')} model={timing.get('model')} "
            f"flags={None if searcher._multi_reranker is None else (searcher._multi_reranker.ollama_available, searcher._multi_reranker.llama_cpp_available)}"
        )
    return rows


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — gate must report, never crash silently
        traceback.print_exc()
        sys.exit(1)
