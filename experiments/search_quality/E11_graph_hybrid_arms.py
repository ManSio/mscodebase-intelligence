#!/usr/bin/env python3
"""
E11 — AST/Graph-hybrid re-ranking РУКИ (read-only, одна сессия).

Гипотеза: NL-запросы кода содержат идентификаторы (file_mtime_ns, notify,
bm25), но подаются в VectorSearch.path без symbol-лукапа (engine._graph_stage
триггерится только на чистый identifier). Подъём graph-хитов (search_symbols)
должен спасти хиты, которые fast/quality теряют.

Руки (над теми же baseline top-k, без перегенерации):
  A-prepend  : graph-файлы в начало списка, затем baseline без дублей
  B-RRF      : reciprocal_rank_fusion(baseline, graph-rank-1)
  C-graph    : graph-хиты подняты наверх (как полностью доверяющий режим)

Метрики: hit@1 / hit@5 / MRR по 10 CASES. Без правок src/, без записи.
"""

import re
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

_STOP = {
    "hot", "reload", "свежест", "индекс", "изменен", "файлов", "файл",
    "help", "is", "and", "or", "the", "table", "колонок", "таблиц", "поиск",
    "похожих", "чанков", "проверка", "факта", "памят", "статус", "удален",
    "эмбеддинг", "измененного", "ранжирование", "результатов", "которые",
    "ключевые", "слова", "медленный", "точный", "один", "схемы", "schema",
    "mismatch", "полный", "rebuild", "переиндексация", "пулы", "путям",
    "проектов", "перестановка", "содержат", "через", "при", "после",
    "before", "after", "query", "output", "index", "value", "list", "map",
    "set", "data", "file", "files", "code", "api", "http", "server",
    "window", "project", "projects", "lancedb", "актуальный", "антипаттерн",
    "build", "builds", "rate", "limit", "big", "old", "status", "реализован",
    "содержит", "не", "по", "для", "как", "когда", "vector", "search",
}


def extract_candidates(query: str, min_len: int = 3) -> list:
    cands: list = []
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+", query):
        t = m.group(0)
        if len(t) >= min_len:
            cands.append(t)
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9._]{1,}", query):
        t = m.group(0)
        if len(t) < min_len:
            continue
        if t.endswith((".", ":", "_", "/")):
            continue
        if t in _STOP or t.lower() in _STOP:
            continue
        if "_" in t:
            continue
        low = t.lower()
        if low == t:
            if len(t) >= 5 or any(ch.isdigit() for ch in t):
                cands.append(t)
            continue
        cands.append(t)
    seen = set()
    uniq = []
    for c in sorted(cands, key=len, reverse=True):
        k = c.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("/")


def hit_position(files: list, expected: str, k: int) -> int:
    want = norm(expected)
    for i, fp in enumerate(files[:k], 1):
        if fp == want or fp.endswith(want):
            return i
    return 0


def reciprocal_rank(r, k=60):
    return 1.0 / (k + r)


def main() -> int:
    import httpx

    for n, u in [("embed", "http://127.0.0.1:8080/health"), ("rerank", "http://127.0.0.1:8081/health")]:
        try:
            ok = httpx.get(u, timeout=3).status_code == 200
        except Exception:
            ok = False
        print(f"{'🟢' if ok else '🔴'} {n} {u}")

    from src.core.di_container import create_service_collection, IndexerFactoryKey
    from src.core.indexing.project_indexer_registry import get_global_registry

    project = ROOT
    services = create_service_collection(project)
    registry = get_global_registry()
    factory = services.resolve(IndexerFactoryKey)
    indexer = registry.get_indexer(project, factory=factory)
    searcher = indexer.searcher
    si = getattr(indexer, "_symbol_index", None) or getattr(indexer, "symbol_index", None)
    print(f"indexer rows={indexer.table.count_rows() if indexer.table else -1}  symbol_index={type(si).__name__ if si else None}")

    arms = {"baseline": [], "A-prepend": [], "B-RRF": [], "C-graph": []}
    perf = {"baseline": 0.0, "graph_lookup": 0.0}

    for i, (q, exp) in enumerate(CASES, 1):
        # baseline
        t0 = time.perf_counter()
        res = searcher.search_with_mode(query=q, mode="quality", limit=5)
        results = res.get("results", []) if isinstance(res, dict) else (res or [])
        base_files = [norm(r.get("metadata", {}).get("file", "")) for r in results]
        perf["baseline"] += (time.perf_counter() - t0) * 1000

        # graph lookup
        t0 = time.perf_counter()
        graph_files = []
        for c in extract_candidates(q):
            try:
                refs = si.search_symbols(c, top_k=15) or []
            except Exception:  # noqa: BLE001
                refs = []
            for x in refs:
                fp = norm(x.file_path)
                if fp not in graph_files:
                    graph_files.append(fp)
        perf["graph_lookup"] += (time.perf_counter() - t0) * 1000

        def prepend(_g, _b):
            out = list(_g) + [f for f in _b if f not in _g]
            return out[:5]

        def rrf(_g, _b):
            scores = {}
            for rank, f in enumerate(_g, 1):
                scores[f] = scores.get(f, 0.0) + reciprocal_rank(rank)
            for rank, f in enumerate(_b, 1):
                scores[f] = scores.get(f, 0.0) + reciprocal_rank(rank)
            return [f for f, _ in sorted(scores.items(), key=lambda kv: -kv[1])][:5]

        def cgraph(_g, _b):
            return (list(_g) + [f for f in _b if f not in _g])[:5]

        arms["baseline"].append((q, exp, base_files, graph_files))
        arms["A-prepend"].append((q, exp, prepend(graph_files, base_files)))
        arms["B-RRF"].append((q, exp, rrf(graph_files, base_files)))
        arms["C-graph"].append((q, exp, cgraph(graph_files, base_files)))

    print("━" * 100)
    hdr = f"{'#':>2} {'base':>4} {'A':>4} {'B':>4} {'C':>4}  эталон  [graph-found файлы]"
    print(hdr)
    sums = {"baseline": (0, 0, 0.0), "A-prepend": (0, 0, 0.0), "B-RRF": (0, 0, 0.0), "C-graph": (0, 0, 0.0)}

    for i, (q, exp, bf, gf) in enumerate(arms["baseline"], 1):
        pos = {}
        mrr = {}
        for arm, lst in [("baseline", bf), ("A-prepend", arms["A-prepend"][i-1][2]),
                         ("B-RRF", arms["B-RRF"][i-1][2]), ("C-graph", arms["C-graph"][i-1][2])]:
            p5 = hit_position(lst, exp, 5)
            p1 = 1 if p5 == 1 else 0
            mr = 1.0 / p5 if p5 else 0.0
            pos[arm] = p5
            mrr[arm] = mr
            h1, hh5, mm = sums[arm]
            sums[arm] = (h1 + p1, hh5 + (1 if p5 else 0), mm + mr)
        marks = {a: ("✅" if pos[a] else "❌") for a in pos}
        gf_str = gf[:2]
        print(
            f"{i:>2} {marks['baseline']}{pos['baseline']:>4} {marks['A-prepend']}{pos['A-prepend']:>4} "
            f"{marks['B-RRF']}{pos['B-RRF']:>4} {marks['C-graph']}{pos['C-graph']:>4}  {norm(exp)}  "
            f"[gf={gf_str}]"
        )

    print("━" * 100)
    print(f"avg baseline_ms={perf['baseline']/len(CASES):.0f}  avg graph_lookup_ms={perf['graph_lookup']/len(CASES):.0f}")
    for arm, (h1, h5, m) in sums.items():
        n = len(CASES)
        print(f"{arm:<10} hit@1={h1}/{n} ({100*h1/n:.0f}%)  hit@5={h5}/{n} ({100*h5/n:.0f}%)  MRR={m/n:.3f}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)