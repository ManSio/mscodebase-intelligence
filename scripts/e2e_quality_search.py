#!/usr/bin/env python3
"""
E2E QUALITY — реальная точность поиска по production-пути (без моков и синтетики).

Отрабатывает претензию «smoke/E2E не проверяет качество, а только что сервисы живы»:
прогоняет РЕАЛЬНЫЕ вопросы по этому репозиторию через ТОТ ЖЕ код, что вызывает
search_code (create_service_collection → ProjectIndexerRegistry → Searcher.search_with_mode),
и сверяет, попадает ли эталонный файл в top-k.

Для каждого вопроса зафиксирован EXPECTED_* — файл, где ответ НАХОДИТСЯ точно
(он выбран экспертно из этого же репозитория, не по свече).

Использование:
  python scripts/e2e_quality_search.py

Exit code: 0 = метрики в допуске; 1 = hit@5 < порога или сервисы не подняты.
"""

import argparse
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# (вопрос, норм. путь эталонного файла, слой)
CASES = [
    (
        "как работает hot-reload свежести индекса при изменении файлов",
        "src/core/indexing/freshness.py",
    ),
    (
        "миграция схемы добавление колонок file_mtime_ns в таблицу LanceDB",
        "src/core/indexing/db_manager.py",
    ),
    (
        "когда таблица пересоздаётся при schema mismatch полный rebuild",
        "src/core/indexing/db_writer.py",
    ),
    (
        "векторный поиск похожих чанков по индексу через LanceDB distance",
        "src/core/search/engine.py",
    ),
    (
        "ленивая проверка факта памяти verify on read статус ADR",
        "src/core/intelligence/verify_on_read.py",
    ),
    (
        "удалённый эмбеддинг через HTTP API llama server batch",
        "src/providers/embedder/remote_embedder.py",
    ),
    (
        "per project indexer registry multi window пулы по путям проектов",
        "src/core/indexing/project_indexer_registry.py",
    ),
    (
        "переиндексация одного изменённого файла notify change rate limit",
        "src/mcp/tools/indexing_tools.py",
    ),
    (
        "ранжирование результатов реранкером BGE M3 перестановка топ",
        "src/providers/reranker/search_result_reranker.py",
    ),
    (
        "bm25 ключевые слова медленный но точный полнотекстовый",
        "src/core/search/bm25.py",
    ),
]


def norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("/")


def hit_at(results: list, expected: str, k: int) -> int:
    """Позиция эталонного файла в первых k (1-indexed) или 0 = промах."""
    want = norm(expected)
    for i, r in enumerate(results[:k]):
        meta = r.get("metadata") or {}
        fp = norm(str(meta.get("file", "")))
        if fp == want or fp.endswith(want):
            return i + 1
    return 0


def build_searcher(project: Path):
    from src.core.di_container import create_service_collection, IndexerFactoryKey
    from src.core.indexing.project_indexer_registry import get_global_registry

    services = create_service_collection(project)
    registry = get_global_registry()
    factory = services.resolve(IndexerFactoryKey)
    indexer = registry.get_indexer(project, factory=factory)
    searcher = indexer.searcher
    print(f"searcher: {type(searcher).__name__}  table rows={_count(indexer)}")
    return searcher


def _count(indexer):
    try:
        return indexer.table.count_rows() if indexer.table is not None else -1
    except Exception:
        return -1


def run_mode(searcher, mode: str, limit: int = 5):
    rows = []
    for q, exp in CASES:
        t0 = time.perf_counter()
        try:
            res = searcher.search_with_mode(query=q, mode=mode, limit=limit)
            results = res.get("results", []) if isinstance(res, dict) else (res or [])
            dt_ms = (time.perf_counter() - t0) * 1000
            top = results[0]["metadata"]["file"] if results else ""
            h1 = hit_at(results, exp, 1)
            h5 = hit_at(results, exp, 5)
            rows.append((q, exp, dt_ms, h1, h5, top))
        except Exception as e:  # noqa: BLE001
            rows.append((q, exp, -1, 0, 0, f"ERR {type(e).__name__}: {e}"))
    return rows


def report(title: str, rows: list) -> tuple[int, int, float]:
    print("━" * 100)
    print(f"## {title}")
    print(f"{'#':>2} {'hit@1':>6} {'hit@5':>6} {'ms':>9}  эталон → топ-файл")
    h1 = h5 = 0
    ms_total = 0.0
    n = len(rows)
    for i, (q, exp, ms, r1, r5, top) in enumerate(rows, 1):
        h1 += 1 if r1 else 0
        h5 += 1 if r5 else 0
        ms_total += ms if ms > 0 else 0.0
        mark = "✅" if r5 else "❌"
        print(
            f"{i:>2} {r1:>6} {r5:>6} {ms:>9.0f}  {mark} {norm(exp)} → {norm(top)}"
        )
    avg = ms_total / max(len([r for r in rows if r[2] > 0]), 1)
    print(f"hit@1={h1}/{n} ({100*h1/n:.0f}%)  hit@5={h5}/{n} ({100*h5/n:.0f}%)  avg_ms={avg:.0f}")
    return h1, h5, avg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(ROOT))
    ap.add_argument("--modes", default="fast,quality")
    ap.add_argument("--min-hit5", type=float, default=0.8, help="порог hit@5 в долях")
    args = ap.parse_args()

    import httpx

    health = {
        n: s
        for n, s in [
            ("embed", "http://127.0.0.1:8080/health"),
            ("rerank", "http://127.0.0.1:8081/health"),
        ]
    }
    for n, u in health.items():
        try:
            ok = httpx.get(u, timeout=3).status_code == 200
        except Exception:
            ok = False
        print(f"{'🟢' if ok else '🔴'} {n} {u}")
        if not ok and n == "embed":
            print("embedder недоступен — тест точности бессмысленен")
            return 1

    project = Path(args.project).resolve()
    searcher = build_searcher(project)

    n_bad = 0
    for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
        rows = run_mode(searcher, mode)
        h1, h5, _ = report(f"mode={mode}", rows)
        if h5 / len(rows) < args.min_hit5:
            n_bad += 1

    print("━" * 100)
    if n_bad == 0:
        print(f"✅ E2E QUALITY: PASSED (hit@5 ≥ {args.min_hit5:.0%} во всех режимах)")
        return 0
    print(f"❌ E2E QUALITY: FAILED (hit@5 < {args.min_hit5:.0%} в {n_bad} режимах)")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)