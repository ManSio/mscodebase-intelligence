"""
WS3 Experiment: Late Enrichment — стоимость и покрытие.

Гипотеза (Late Code Chunking, ACL 2026): обогащение результатов ПОСЛЕ retrieval
дёшево и добавляет полезный контекст. Измеряем на реальном коде:

  - enrichment_ms: латентность _late_enrich_results на топ-10
  - tokens_added:  оценка добавленных токенов (chars/4)
  - coverage:      % результатов с module / parent_symbol / chunk_headline / imports

Фазы:
  1. live   — реальный Searcher через DI (индекс из системной папки).
              Если индекс пуст — честный fallback на фазу 2.
  2. chunks — real chunk-фикстуры из исходников проекта (без индекса).

Run:
  python experiments/late_enrichment/bench.py --phase auto
  python experiments/late_enrichment/bench.py --phase chunks
"""
import argparse
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXT = Path(
    os.getenv(
        "EXT_ROOT",
        r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence",
    )
)
# ВАЖНО: EXT вставляем первым, PROJECT_ROOT — ПОСЛЕДНИМ, чтобы исходники
# проекта (с актуальными правками) были в sys.path[0] и перекрывали
# устаревшую копию в расширении.
for p in (str(EXT), str(PROJECT_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import sys as _sys

    if _sys.stdout.encoding != "utf-8":
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

os.environ.setdefault("PYTHONPATH", str(EXT))
os.environ["PROJECT_PATH"] = str(PROJECT_ROOT)

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

QUERIES = [
    "notify_change index update workflow",
    "impact_analysis callers callees graph",
    "commit_memory semantic commits cache",
    "hybrid_search reranker rrf fusion",
    "PID lock startup diagnostics",
    "artifact_paths data root migration",
    "property graph imports edges",
    "modification guard impact token",
]


def _load_texts() -> list[dict]:
    """Реальные файлы проекта → chunk-фикстуры с metadata."""
    texts = []
    files = sorted(PROJECT_ROOT.rglob("*.py"))
    for f in files[:60]:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = content.splitlines()
        # берём куски по 30 строк как «чанки»
        for i in range(0, len(lines), 30):
            chunk = "\n".join(lines[i : i + 30])
            if len(chunk) < 40:
                continue
            rel = f.relative_to(PROJECT_ROOT).as_posix()
            texts.append(
                {
                    "text": chunk,
                    "final_score": 0.5,
                    "metadata": {
                        "file": rel,
                        "chunk_index": i // 30,
                        "layer": rel.split("/")[0],
                    },
                }
            )
        if len(texts) >= 60:
            break
    return texts


def bench_enrich(searcher, results: list[dict], query: str) -> dict:
    """Замер одного прогона enrichment."""
    t0 = time.perf_counter()
    enriched = searcher._late_enrich_results(list(results), query)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    total_tokens = 0
    coverage = {"module": 0, "parent_symbol": 0, "chunk_headline": 0, "imports": 0}
    total = 0
    for r in enriched:
        meta = r.get("metadata", {}) or {}
        extra = meta.get("context_extra", {})
        if not extra:
            continue
        total += 1
        for key in coverage:
            if extra.get(key):
                coverage[key] += 1
        total_tokens += meta.get("enrichment_tokens", 0) or 0

    return {
        "query": query[:50],
        "results": len(enriched),
        "enriched": total,
        "enrichment_ms": round(elapsed_ms, 3),
        "tokens_added": total_tokens,
        "coverage": {k: round(v / max(total, 1), 3) for k, v in coverage.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="auto", choices=["auto", "live", "chunks"])
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    from src.core.search.engine import Searcher

    searcher = Searcher(indexer=None, embedder=None)
    searcher._late_enrichment = True

    results_pool = None
    live = False
    if args.phase in ("auto", "live"):
        try:
            from src.core.artifact_paths import get_db_path
            from src.core.di_container import create_service_collection
            from src.core.indexing.file_guard import FileGuard
            from src.core.indexing.indexer import Indexer
            from src.core.indexing.parser import CodeParser
            from src.core.indexing.symbol_index import SymbolIndex
            from src.providers.embedder.remote_embedder import RemoteEmbedder

            services = create_service_collection(PROJECT_ROOT)
            embedder = services.resolve(RemoteEmbedder)
            db_path = get_db_path(PROJECT_ROOT)
            indexer = Indexer(
                db_path=db_path,
                embedder=embedder,
                file_guard=FileGuard(PROJECT_ROOT),
                project_path=PROJECT_ROOT,
                parser=CodeParser(),
                symbol_index=SymbolIndex(),
            )
            live_searcher = Searcher(indexer, embedder)
            live_searcher._late_enrichment = True
            status = indexer.get_status() if hasattr(indexer, "get_status") else {}
            chunks = status.get("total_chunks", 0) if isinstance(status, dict) else 0
            if chunks > 0:
                # живой поиск по первому запросу → реальные результаты
                live_results = live_searcher.hybrid_search(
                    QUERIES[0], limit=args.limit
                )
                if live_results:
                    results_pool = live_results
                    live = True
            indexer.close()
        except Exception as e:  # noqa: BLE001
            print(f"[bench] live-фаза недоступна ({e}) — фаза chunks", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    if results_pool is None:
        results_pool = _load_texts()[: args.limit]
        print(
            f"[bench] фаза=chunks: {len(results_pool)} реальных чанков проекта",
            file=sys.stderr,
        )

    reports = [bench_enrich(searcher, results_pool, q) for q in QUERIES]
    # агрегат
    agg = {
        "phase": "live" if live else "chunks",
        "queries": len(reports),
        "avg_enrichment_ms": round(
            sum(r["enrichment_ms"] for r in reports) / len(reports), 3
        ),
        "avg_tokens_added": round(
            sum(r["tokens_added"] for r in reports) / len(reports), 1
        ),
        "avg_coverage": {
            k: round(sum(r["coverage"][k] for r in reports) / len(reports), 3)
            for k in ("module", "parent_symbol", "chunk_headline", "imports")
        },
    }
    print(json.dumps(agg, ensure_ascii=False, indent=2))
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
