#!/usr/bin/env python3
"""
E10 (2026-09-19): Full-text embedding + prefixed e5 + RRF pool>=50.

Хипотеза: hit@1/hit@5 падают, потому что:
  - эмбеддится COMPACT (подпись+3 строки / [:500]) вместо ПОЛНОГО тела
    функции (BATCH_SIZE живёт в text_full, вектор слеп),
  - llama.cpp-ветка embedder'а не ставит e5-префиксы query:/passage:,
  - per-site кандидатный пул для RRF = 10 (limit*overfetch=5*2), а нужно >=50.

Эксперимент изолирован: MSCODEBASE_DATA_DIR -> temp/mscodebase_exp_e10,
прод-индекс и runtime MCP не трогаются. Методика = scripts/e2e_quality_search.py
(production-путь create_service_collection -> ProjectIndexerRegistry -> search_with_mode).
1 замер на новом индексе; 'было' = baseline до правок (fast 0/50%, quality 30/30%).
"""

import importlib.util
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TMP_DIR = Path(os.environ.get("TEMP", "/tmp")) / "mscodebase_exp_e10"
os.environ["MSCODEBASE_DATA_DIR"] = str(TMP_DIR)
os.environ["OVERFETCH_FACTOR"] = "10"
os.environ.setdefault("MAX_RERANKER_INPUT", "50")

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def load_e2e_module() -> object:
    spec = importlib.util.spec_from_file_location(
        "e2e_quality_search", ROOT / "scripts" / "e2e_quality_search.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    import httpx

    for n, u in [
        ("embed", "http://127.0.0.1:8080/health"),
        ("rerank", "http://127.0.0.1:8081/health"),
    ]:
        try:
            ok = httpx.get(u, timeout=3).status_code == 200
        except Exception:
            ok = False
        print(f"{'OK ' if ok else 'ERR'} {n}")

    from src.core.di_container import IndexerFactoryKey, create_service_collection
    from src.core.indexing.project_indexer_registry import get_global_registry

    project = ROOT
    services = create_service_collection(project)
    registry = get_global_registry()
    factory = services.resolve(IndexerFactoryKey)
    indexer = registry.get_indexer(project, factory=factory)

    print(f"isolated data root: {TMP_DIR}")
    t0 = time.perf_counter()
    n = indexer.index_project(project)
    dt = time.perf_counter() - t0
    rows = indexer.table.count_rows() if indexer.table is not None else -1
    print(f"indexed files={n} rows={rows} in {dt:.1f}s")

    e2e = load_e2e_module()
    searcher = indexer.searcher
    for mode in ("fast", "quality"):
        rows_out = e2e.run_mode(searcher, mode)
        e2e.report(f"mode={mode}", rows_out)

    print("TMP_DIR (не забыть очистить): " + str(TMP_DIR))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)