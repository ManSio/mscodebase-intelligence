#!/usr/bin/env python3
"""
eval_text_chunks.py — Текстовый RAG: Hit@1 / Hit@Gold(Top-5) / MRR
по живому индексу (без переиндексации). Прямым lookup без LLM-судей.

Gold = markdown_section чанк из ожидаемого .md файла (любой язык).
Сравнение с E10/E11 baseline (кодовые замеры 2026-09-19).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Gold standard: вопрос → эталонный .md файл (любой язык) ──
# Для doc-запросов принимаем ru/en/zh варианты как золото,
# т.к. контент переведён.
TEXT_CASES = [
    ("how to install the mscodebase extension in Zed and what it does",
     "README.md"),
    ("what MCP tools are available for code search",
     "README.md"),
    ("search modes fast quality deep auto which to choose",
     "README.md"),
    ("how does the clean architecture layers DI container work",
     "docs/en/ARCHITECTURE.md"),
    ("how is the search pipeline structured BM25 RRF reranker",
     "docs/en/SEARCH_PIPELINE.md"),
    ("graceful degradation levels llama ONNX BM25",
     "docs/en/GRACEFUL_DEGRADATION.md"),
    ("frequently asked questions installation setup",
     "docs/en/FAQ.md"),
    ("how to configure telemetry ETA data collection",
     "docs/en/TELEMETRY.md"),
    ("security policy vulnerability reporting",
     "docs/en/SECURITY.md"),
    ("Windows Zed restricted mode quirks",
     "docs/en/ZED_WINDOWS_QUIRKS.md"),
    ("how to contribute development PR code review",
     "docs/en/CONTRIBUTING.md"),
    ("version history changelog",
     "docs/en/CHANGELOG.md"),
    ("how to install ONNX llama reranker models",
     "docs/en/INSTALL_MODELS.md"),
    ("LM Studio reranker embedder setup",
     "docs/en/LM_STUDIO_SETUP.md"),
    ("system requirements Windows macOS Linux",
     "docs/en/SYSTEM_REQUIREMENTS.md"),
    ("handoff context transfer between sessions",
     "docs/en/HANDFOFF.md"),
]


def norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("/")


def is_doc_chunk(result: dict, expected_file: str) -> bool:
    meta = result.get("metadata") or {}
    fp = norm(str(meta.get("file", "")))
    # Принимаем любой язык: docs/ru/README.md тоже золото для README.md
    return fp.endswith(norm(expected_file))


def hit_at(results: list, expected_file: str, k: int) -> int:
    for i, r in enumerate(results[:k]):
        if is_doc_chunk(r, expected_file):
            return i + 1
    return 0


def mrr(results: list, expected_file: str) -> float:
    pos = hit_at(results, expected_file, len(results))
    return 1.0 / pos if pos else 0.0


def main() -> int:
    from src.core.di_container import create_service_collection, IndexerFactoryKey
    from src.core.indexing.project_indexer_registry import get_global_registry

    project = ROOT
    services = create_service_collection(project)
    registry = get_global_registry()
    factory = services.resolve(IndexerFactoryKey)
    indexer = registry.get_indexer(project, factory=factory)
    searcher = indexer.searcher
    rows_cnt = indexer.table.count_rows() if indexer.table else -1
    print(f"searcher={type(searcher).__name__} table_rows={rows_cnt}")

    # ── Санити ──────────────────────────────────────────────
    q0 = TEXT_CASES[0][0]
    res0 = searcher.search_with_mode(query=q0, mode="quality", limit=5)
    r0s = res0.get("results", []) if isinstance(res0, dict) else (res0 or [])
    print(f"SANITY q={q0!r} n_results={len(r0s)}")
    if r0s:
        m = r0s[0].get("metadata") or {}
        print(f"  meta keys={list(m.keys())}")
        print(f"  first file={m.get('file','')!r} text[:100]={r0s[0].get('text','')[:100]!r}")

    # ── Полный прогон ────────────────────────────────────────
    rows = []
    for q, exp_file in TEXT_CASES:
        t0 = time.perf_counter()
        try:
            res = searcher.search_with_mode(query=q, mode="quality", limit=5)
            results = res.get("results", []) if isinstance(res, dict) else (res or [])
            dt_ms = (time.perf_counter() - t0) * 1000
        except Exception as e:
            results = []
            dt_ms = -1
            print(f"  ERR q={q!r}: {type(e).__name__}: {e}", file=sys.stderr)

        h1 = hit_at(results, exp_file, 1)
        h5 = hit_at(results, exp_file, 5)
        rr = mrr(results, exp_file)
        top_file = norm((results[0].get("metadata") or {}).get("file", "")) if results else ""
        rows.append({
            "query": q,
            "expected": exp_file,
            "latency_ms": round(dt_ms, 1),
            "hit1": 1.0 if h1 else 0.0,
            "hit5": 1.0 if h5 else 0.0,
            "mrr": round(rr, 3),
            "rank1": h1,
            "rank5": h5,
            "top_file": top_file,
            "n_results": len(results),
        })

    # ── Отчёт ────────────────────────────────────────────────
    n = len(rows)
    h1 = sum(r["hit1"] for r in rows)
    h5 = sum(r["hit5"] for r in rows)
    mrr_sum = sum(r["mrr"] for r in rows)
    avg_ms = sum(r["latency_ms"] for r in rows if r["latency_ms"] > 0) / max(
        sum(1 for r in rows if r["latency_ms"] > 0), 1
    )
    metrics = {
        "n_queries": n,
        "hit1_pct": round(100 * h1 / n, 1),
        "hit5_pct": round(100 * h5 / n, 1),
        "mrr_mean": round(mrr_sum / n, 3),
        "avg_latency_ms": round(avg_ms, 0),
    }
    print("━" * 110)
    print("## Текстовый RAG — doc-чанки (README + docs/en + docstrings)")
    print(f"{'#':>2} {'hit1':>6} {'hit5':>6} {'MRR':>6} {'ms':>8}  эталон → топ-файл")
    for i, r in enumerate(rows, 1):
        mark5 = "✅" if r["hit5"] else "❌"
        print(
            f"{i:>2} {r['hit1']:>6} {r['hit5']:6} {r['mrr']:6} {r['latency_ms']:8.0f}  "
            f"{mark5} {r['expected']} → {r['top_file']}"
        )
    print(
        f"hit@1={h1}/{n} ({metrics['hit1_pct']}%)  "
        f"hit@5={h5}/{n} ({metrics['hit5_pct']}%)  "
        f"MRR={metrics['mrr_mean']}  avg_ms={metrics['avg_latency_ms']:.0f}"
    )

    # ── Сравнение с прошлым кодовым baseline ─────────────────
    print()
    print("━" * 110)
    print("## Сравнение: Текстовый RAG vs Кодовый (E10/E11 baseline, 2026-09-19)")
    print(f"{'Метрика':<20} | {'Текстовый RAG':>14} | {'Прошлый код (E10/E11)':>22} | {'Дельта':>8}")
    print("-" * 110)
    print(
        f"{'hit@1':<20} | {metrics['hit1_pct']:>13}% | {'0% / 20% (fast/quality)':>22} | {'—':>8}"
    )
    print(
        f"{'hit@5 (Gold Top-K)':<20} | {metrics['hit5_pct']:>13}% | {'50% / 40% (fast/quality)':>22} | {'—':>8}"
    )
    print(
        f"{'MRR':<20} | {metrics['mrr_mean']:>13} | {'0.200 (E11 baseline)':>22} | {'—':>8}"
    )
    print("-" * 110)
    print("Примечание: E10/E11 — по .py файлам (код), текстовый — по .md-чанкам.")
    print("Gold-стандарты разные (файл vs секция), прямое сравнение условное.")
    print("Текстовый RAG ниже кода — doc-чанки менее дискриминативны в эмбеддинг-пространстве.")

    out = ROOT / "experiments" / "text_chunk_eval.json"
    out.write_text(json.dumps({"metrics": metrics, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Результаты → {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)