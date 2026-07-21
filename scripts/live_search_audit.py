"""
Live search_code audit harness for MSCodeBase Intelligence.

Mirrors the MCP server's DI wiring (src/core/di_container.py) but runs
standalone so we can load-test every search_code mode + the reranker even
when the Zed-managed MCP process is down.

Key facts:
- Loads .env (so ONNX_PROVIDERS=openvino is honored -> ~350 ch/s, not 17).
- Rebuilds a CLEAN index (the on-disk LanceDB was corrupt/empty).
- Exercises search_with_mode for fast/quality/deep/auto/context and the
  MultiProviderReranker directly with many queries.
"""

import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

# --- bootstrap env (same as src/main.py:_load_env) -------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXT = Path(os.getenv("EXT_ROOT", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
if str(EXT) not in sys.path:
    sys.path.insert(0, str(EXT))

try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[env] loaded {env_path}")
    else:
        print(f"[env] NO .env at {env_path} (using system env)")
except ImportError:
    print("[env] python-dotenv missing")

# Make `src.*` importable
if str(EXT) not in sys.path:
    sys.path.insert(0, str(EXT))
os.environ.setdefault("PYTHONPATH", str(EXT))
os.environ["PROJECT_PATH"] = str(PROJECT_ROOT)

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S", stream=sys.stderr)

from src.config.settings import get_config
from src.core.indexing.file_guard import FileGuard
from src.providers.embedder.remote_embedder import RemoteEmbedder
from src.core.indexing.indexer import Indexer, _generate_unique_db_path
from src.core.search.engine import Searcher
from src.core.di_container import create_service_collection
from src.providers.reranker.multi_provider import MultiProviderReranker


def build_wired_stack(project_root: Path):
    """Replicate DI wiring from create_service_collection + indexer factory."""
    services = create_service_collection(project_root)
    embedder = services.resolve(RemoteEmbedder)
    db_path = _generate_unique_db_path(project_root)
    file_guard = FileGuard(project_root)
    from src.core.indexing.parser import CodeParser
        parser = CodeParser()
        from src.core.indexing.symbol_index import SymbolIndex
    symbol_index = SymbolIndex()
    indexer = Indexer(
        db_path=db_path,
        embedder=embedder,
        file_guard=file_guard,
        project_path=project_root,
        parser=parser,
        symbol_index=symbol_index,
    )
    searcher = Searcher(indexer, embedder)
    indexer.set_searcher(searcher)
    return embedder, indexer, searcher, db_path


async def ensure_reranker(searcher: Searcher) -> MultiProviderReranker:
    rr = await searcher._ensure_multi_reranker_async()
    return rr


def summarize_results(res: dict, n: int = 5) -> str:
    results = res.get("results", []) or []
    lines = []
    for i, r in enumerate(results[:n], 1):
        meta = r.get("metadata", {}) or {}
        f = meta.get("file", "?")
        score = r.get("final_score", r.get("score", "?"))
        lines.append(f"  {i}. [{score}] {f}")
    if not lines:
        lines.append("  (no results)")
    return "\n".join(lines)


async def main():
    project_root = PROJECT_ROOT.resolve()
    print(f"[setup] project_root = {project_root}")

    embedder, indexer, searcher, db_path = build_wired_stack(project_root)
    print(f"[setup] db_path = {db_path}")

    # --- warm embedder (loads ONNX/OpenVINO in-process) -------------------
    print("[warmup] initializing provider (OpenVINO/ONNX in-process)...")
    embedder._init_provider_async()
    print(f"[warmup] mode={getattr(embedder,'mode',None)} ov_compiled={getattr(embedder,'_ov_compiled',None)}")
    print("[warmup] embedding a probe query to load model...")
    t0 = time.perf_counter()
    probe = embedder.embed("probe query for warmup", is_query=True)
    dt = (time.perf_counter() - t0) * 1000
    print(f"[warmup] embed dim={len(probe)} in {dt:.1f}ms  providers={getattr(embedder,'_active_provider',None)}")

    # --- clean rebuild ----------------------------------------------------
    import shutil
    db_dir = db_path.parent
    if db_dir.exists():
        print(f"[reindex] removing corrupt index dir: {db_dir}")
        shutil.rmtree(db_dir, ignore_errors=True)
    print("[reindex] building clean index (this is the slow part)...")
    t0 = time.perf_counter()
    indexed = await asyncio.to_thread(indexer.index_project, project_root)
    dt = (time.perf_counter() - t0)
    # build BM25
    searcher.reindex()
    print(f"[reindex] indexed {indexed} files in {dt:.1f}s")

    # count chunks
    try:
        n_chunks = indexer.table.count_rows() if indexer.table is not None else 0
    except Exception as e:
        n_chunks = f"err:{e}"
    print(f"[reindex] chunks in table = {n_chunks}")

    # --- reranker ---------------------------------------------------------
    print("[reranker] initializing MultiProviderReranker...")
    rr = await ensure_reranker(searcher)
    if rr is not None:
        print(f"[reranker] lm_studio={rr.lm_studio_available} ollama={rr.ollama_available} llama_cpp={rr.llama_cpp_available}")
    else:
        print("[reranker] NOT available (no external provider)")

    # --- queries ----------------------------------------------------------
    queries = [
        "def hybrid_search_async",
        "embed_batch ONNX OpenVINO",
        "reranker bge-m3 llama-server",
        "index_guard schema validation vector dim",
        "file_guard should_skip_file relative path",
        "intel_auto_collect_adrs git log async",
        "Cypher OPTIONAL MATCH LEFT JOIN",
        "PropertyGraph ASSIGNED_FROM edge",
        "search_with_mode fast quality deep dispatch",
        "LanceDB IVF index build",
        "SymbolIndexAdapter pure mode",
        "notify_change meta patching apply_file_move",
        "graceful degradation embedder fallback",
        "chunk parser MAX_CHUNK_CHARS truncation",
        "rerank reciprocal rank fusion RRF",
    ]

    modes = ["fast", "quality", "deep", "auto", "context"]
    report = {}
    for q in queries:
        report[q] = {}
        for mode in modes:
            try:
                t0 = time.perf_counter()
                res = searcher.search_with_mode(q, mode=mode, limit=5)
                dt = (time.perf_counter() - t0) * 1000
                n = len(res.get("results", []) or [])
                report[q][mode] = (n, dt)
                print(f"\n=== Q: {q!r} | mode={mode} | results={n} | {dt:.0f}ms ===")
                print(summarize_results(res))
            except Exception as e:
                report[q][mode] = ("ERR", str(e)[:80])
                print(f"\n=== Q: {q!r} | mode={mode} | ERROR: {e} ===")
                traceback.print_exc()

    # --- direct reranker load test ---------------------------------------
    if rr is not None and rr.lm_studio_available or (rr is not None and rr.ollama_available) or (rr is not None and rr.llama_cpp_available):
        print("\n=== RERANKER LOAD TEST ===")
        # grab some texts from a quality search to rerank
        sample = searcher.search_with_mode("indexer LanceDB vector search", mode="quality", limit=10)
        texts = [r.get("text", "") for r in sample.get("results", [])]
        if texts:
            for _ in range(5):
                t0 = time.perf_counter()
                ranked = await rr.rerank("indexer LanceDB vector search", texts)
                dt = (time.perf_counter() - t0) * 1000
                print(f"  rerank {len(texts)} texts -> {len(ranked)} in {dt:.0f}ms")
    else:
        print("\n[reranker] SKIP load test: no external provider available")

    # --- summary table ----------------------------------------------------
    print("\n================ SUMMARY (results_count, ms) ================")
    header = "query".ljust(40) + "".join(m.ljust(12) for m in modes)
    print(header)
    for q, mdict in report.items():
        row = q[:38].ljust(40)
        for m in modes:
            v = mdict.get(m, ("?", "?"))
            if isinstance(v, tuple):
                cell = f"{v[0]}/{v[1]:.0f}" if isinstance(v[1], (int, float)) else str(v[0])
            else:
                cell = str(v)
            row += cell.ljust(12)
        print(row)

    await searcher.close()


if __name__ == "__main__":
    asyncio.run(main())
