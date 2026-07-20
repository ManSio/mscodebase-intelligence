"""
A-stage: diagnose search_code timeout by measuring each pipeline stage.

Mirrors live_search_audit.py DI wiring but times individual stages:
  - embed (query vector)
  - dense vector search (LanceDB)
  - bm25 search (in-memory)
  - multi-reranker (llama.cpp / LM Studio)
  - fts5 build (to_pandas over full table) + fts5 search

Run:
  python scripts/benchmark_search_stages.py "def hybrid_search" --mode quality
"""
import argparse
import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXT = Path(os.getenv("EXT_ROOT", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
for p in (str(EXT),):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[env] loaded {env_path}")
except ImportError:
    pass

os.environ.setdefault("PYTHONPATH", str(EXT))
os.environ["PROJECT_PATH"] = str(PROJECT_ROOT)

import logging
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S", stream=sys.stderr)

from src.core.config import get_config
from src.core.file_guard import FileGuard
from src.core.remote_embedder import RemoteEmbedder
from src.core.indexer import Indexer, _generate_unique_db_path
from src.core.searcher import Searcher
from src.core.di_container import create_service_collection


def build_wired_stack(project_root: Path):
    services = create_service_collection(project_root)
    embedder = services.resolve(RemoteEmbedder)
    db_path = _generate_unique_db_path(project_root)
    file_guard = FileGuard(project_root)
    from src.core.parser import CodeParser
    from src.core.symbol_index import SymbolIndex
    parser = CodeParser()
    symbol_index = SymbolIndex()
    indexer = Indexer(
        db_path=db_path, embedder=embedder, file_guard=file_guard,
        project_path=project_root, parser=parser, symbol_index=symbol_index,
    )
    searcher = Searcher(indexer, embedder)
    indexer.set_searcher(searcher)
    return embedder, indexer, searcher, db_path


async def time_embed(searcher, query):
    t0 = time.perf_counter()
    vec = searcher.embedder.embed(query)
    return time.perf_counter() - t0, vec


async def time_dense(searcher, vec, limit):
    t0 = time.perf_counter()
    res = await searcher._vector_search_async(vec, limit=limit)
    return time.perf_counter() - t0, res


async def time_bm25(searcher, query, limit):
    t0 = time.perf_counter()
    res = await searcher._bm25_search_async(query, limit=limit)
    return time.perf_counter() - t0, res


async def time_reranker(searcher, query, results, limit):
    t0 = time.perf_counter()
    try:
        rr = await searcher._ensure_multi_reranker_async()
        if rr is None:
            return time.perf_counter() - t0, "reranker=None (unavailable)"
        out = await searcher._apply_multi_reranker_async(query, results, limit)
        return time.perf_counter() - t0, f"{len(out)} results"
    except Exception as e:
        return time.perf_counter() - t0, f"ERROR: {e}"


async def time_fts5_build(searcher):
    t0 = time.perf_counter()
    try:
        searcher._build_fts5_index()
        return time.perf_counter() - t0, "built"
    except Exception as e:
        return time.perf_counter() - t0, f"ERROR: {e}"


async def time_fts5_search(searcher, query, limit):
    t0 = time.perf_counter()
    try:
        res = searcher._fts5_search(query, limit=limit)
        return time.perf_counter() - t0, f"{len(res)} results"
    except Exception as e:
        return time.perf_counter() - t0, f"ERROR: {e}"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", default="def hybrid_search")
    ap.add_argument("--mode", default="quality")
    ap.add_argument("--limit", type=int, default=6)
    args = ap.parse_args()

    print(f"[*] Building stack for {PROJECT_ROOT}")
    embedder, indexer, searcher, db_path = build_wired_stack(PROJECT_ROOT)

    # Ensure index is loaded
    try:
        n = indexer.table.count_rows() if indexer.table is not None else 0
        print(f"[*] Index rows: {n}")
        if n == 0:
            print("[!] Index empty — run intel_trigger_reindex first. Aborting stage timing.")
            return
    except Exception as e:
        print(f"[!] Cannot read index: {e}")
        return

    limit = args.limit
    query = args.query

    print(f"\n=== Stage timing for query={query!r} mode={args.mode} ===")

    embed_s, vec = await time_embed(searcher, query)
    print(f"  embed            : {embed_s*1000:8.1f} ms  (vec={'yes' if vec else 'NO'})")

    dense_s, dense = await time_dense(searcher, vec, limit)
    print(f"  dense (LanceDB)  : {dense_s*1000:8.1f} ms  ({len(dense)} results)")

    bm25_s, bm = await time_bm25(searcher, query, limit)
    print(f"  bm25 (in-mem)    : {bm25_s*1000:8.1f} ms  ({len(bm)} results)")

    # reranker needs pre_rerank results — synthesize from dense+bm25
    pre = (dense[:limit] if dense else bm[:limit])
    rr_s, rr_info = await time_reranker(searcher, query, pre, limit)
    print(f"  reranker         : {rr_s*1000:8.1f} ms  ({rr_info})")

    fts5b_s, fts5b_info = await time_fts5_build(searcher)
    print(f"  fts5 build       : {fts5b_s*1000:8.1f} ms  ({fts5b_info})")

    fts5s_s, fts5s_info = await time_fts5_search(searcher, query, limit)
    print(f"  fts5 search      : {fts5s_s*1000:8.1f} ms  ({fts5s_info})")

    # Full end-to-end search_with_mode
    t0 = time.perf_counter()
    try:
        res = searcher.search_with_mode(query, mode=args.mode, limit=limit)
        end2end = time.perf_counter() - t0
        nres = len(res.get("results", [])) if isinstance(res, dict) else 0
        print(f"  END-TO-END {args.mode:8}: {end2end*1000:8.1f} ms  ({nres} results)")
    except Exception as e:
        print(f"  END-TO-END ERROR: {e}")
        traceback.print_exc()

    # Sum of independent stages vs 15s timeout
    total_indep = embed_s + dense_s + bm25_s + (rr_s if isinstance(rr_s, float) else 0)
    print(f"\n[*] Sum of embed+dense+bm25+reranker (serial estimate): {total_indep*1000:.1f} ms")
    print(f"[*] search_code timeout_ms = 15000 ms")
    print(f"[*] fts5 build is ONE-TIME (cached after first call)")


if __name__ == "__main__":
    asyncio.run(main())
