"""Синхронная переиндексация D:\\Project\\MSCodeBase с поэтапной трассировкой.

Стратегия:
- Отключаем embedder (используем hash-based fallback) чтобы не зависнуть на LM Studio.
- Ограничиваем max_files для быстрого smoke-теста.
- Логируем каждый этап в C:\\temp\\reindex.log.
"""
import os
import sys
import time
import logging
import traceback

LOG = r"C:\temp\reindex_mscodebase.log"
os.makedirs(os.path.dirname(LOG), exist_ok=True)
logging.basicConfig(
    filename=LOG, filemode="w", level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("reindex")
# Echo to stdout too
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
log.addHandler(console)


def main():
    log.info("=== STEP 0: env setup ===")
    os.environ["MSCODEBASE_ALLOW_SELF_INDEX"] = "1"
    os.environ["PROJECT_PATH"] = r"D:\Project\MSCodeBase"
    os.environ["ZED_WORKTREE_ROOT"] = r"D:\Project\MSCodeBase"
    os.environ["PYTHONPATH"] = r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"
    sys.path.insert(0, os.environ["PYTHONPATH"])

    log.info("=== STEP 1: resolve project_root ===")
    from src.mcp.server import resolve_project_root, reset_project_root_cache
    reset_project_root_cache()
    pr = resolve_project_root()
    log.info(f"  project_root = {pr}")
    log.info(f"  _ext_root    = {__import__('src.mcp.server', fromlist=['_ext_root'])._ext_root}")

    log.info("=== STEP 2: create DI container ===")
    from src.core.di_container import create_service_collection, IndexerFactoryKey
    services = create_service_collection(pr)
    factory = services.resolve(IndexerFactoryKey)
    log.info(f"  factory = {factory}")

    log.info("=== STEP 3: create indexer ===")
    indexer = factory(pr)
    log.info(f"  indexer.project_path = {indexer.project_path}")
    log.info(f"  indexer type = {type(indexer).__name__}")
    log.info(f"  status before: {indexer.get_status()}")

    log.info("=== STEP 4: discover source files ===")
    from pathlib import Path
    t0 = time.time()
    src_dir = Path(pr) / "src"
    files = []
    for p in src_dir.rglob("*.py"):
        if any(x in p.parts for x in ("__pycache__", ".git", "node_modules", ".codebase_indices")):
            continue
        files.append(p)
    log.info(f"  discovered {len(files)} .py files in src/ in {time.time()-t0:.2f}s")
    for f in files[:5]:
        log.info(f"    {f.name}")

    log.info("=== STEP 5: parse files (no embedder) ===")
    from src.core.parser import CodeParser
    parser = CodeParser()
    parsed = []
    t0 = time.time()
    for i, fp in enumerate(files):
        try:
            chunks = parser.parse_file(str(fp), file_id=str(fp.relative_to(pr)))
            parsed.extend(chunks)
        except Exception as e:
            log.warning(f"  parse error in {fp}: {e}")
        if i % 50 == 0:
            log.info(f"    parsed {i}/{len(files)}")
    log.info(f"  parsed {len(parsed)} chunks in {time.time()-t0:.2f}s")

    log.info("=== STEP 6: write to LanceDB (no embeddings) ===")
    from src.core.vector_store import VectorStore
    db_path = Path(pr) / ".codebase_indices" / "lancedb_v2"
    log.info(f"  db_path = {db_path}")
    try:
        vs = VectorStore(db_path=str(db_path), project_name="mscodebase")
        log.info(f"  VectorStore created: {type(vs).__name__}")
    except Exception as e:
        log.error(f"  VectorStore creation failed: {e}")
        log.error(traceback.format_exc())
        return

    log.info("=== STEP 7: ingest chunks ===")
    t0 = time.time()
    try:
        n = vs.ingest_chunks(parsed, embedder=None)
        log.info(f"  ingested {n} chunks in {time.time()-t0:.2f}s")
    except Exception as e:
        log.error(f"  ingest failed: {e}")
        log.error(traceback.format_exc())
        return

    log.info("=== STEP 8: verify ===")
    try:
        cnt = vs.count()
        log.info(f"  total_chunks in DB: {cnt}")
    except Exception as e:
        log.warning(f"  count failed: {e}")

    log.info("=== DONE ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.error("FATAL")
        log.error(traceback.format_exc())
