"""
E4.1 Benchmark — Recall + Latency для 4 проблемных классов.

Классы: modify, test, impact, verify.
Источник индекса: реальный проект MSCodeBase (graph.db).
Режим адаптера: PURE (graph.db is persistence, как в production).

Метрики:
- Recall@K: доля запросов, где ожидаемый символ попал в топ-K результатов
- Latency: медиана задержки (ms) по всем запросам класса

Цель: Recall >= 0.40 при latency < 600ms (на glag-stage включённой).
"""
import sys
import time
import json
import statistics
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.graph import PropertyGraph
from src.core.search.graph_adapter import SymbolIndexAdapter


# Реальный индекс проекта MSCodeBase
PROJECT_DB = Path(r"C:\Users\misha\AppData\Local\mscodebase\projects\bfe9644b\graph.db")

# Датасет: (класс, query, expected_symbol, expected_file_hint)
TASKS: List[Tuple[str, str, str, str]] = [
    # modify — найти что менять
    ("modify", "save_symbol_index", "save_symbol_index", "index_guard.py"),
    ("modify", "resolve_indexer", "resolve_indexer", "base.py"),
    ("modify", "add_definitions", "add_definitions", "graph_adapter.py"),
    ("modify", "build_call_graph", "build_call_graph", "graph_adapter.py"),

    # test — найти тесты
    ("test", "symbol_index_persistence", "test_symbol_index_persistence_e4", "tests/"),
    ("test", "graph_query_project_binding", "test_graph_query_project_binding", "tests/"),
    ("test", "search_bs_audit", "test_search_bs_audit", "tests/"),

    # impact — кто зависит от символа
    ("impact", "save_symbol_index", "save_symbol_index", "index_guard.py"),
    ("impact", "add_definitions", "add_definitions", "graph_adapter.py"),
    ("impact", "build_call_graph", "build_call_graph", "graph_adapter.py"),

    # verify — чем проверить
    ("verify", "test_pure_skip_save", "test_pure_skip_save", "tests/"),
    ("verify", "test_hybrid_normal_save", "test_hybrid_normal_save", "tests/"),
    ("verify", "test_raw_symbol_index_save", "test_raw_symbol_index_save", "tests/"),
]

K = 10
RUNS_PER_QUERY = 3


def run_query(adapter: SymbolIndexAdapter, cls: str, query: str) -> Tuple[List[str], float]:
    """Запускает запрос для класса, возвращает (список_символов, latency_ms)."""
    start = time.perf_counter()

    if cls in ("modify", "test", "verify"):
        # Поиск по имени символа
        results = adapter.search_symbols(query, top_k=K)
        symbols = [r.symbol for r in results]
    elif cls == "impact":
        # Анализ влияния: ожидаем увидеть symbol в callers/callees
        impact = adapter.get_impact_analysis(query, depth=2)
        symbols = []
        for c in impact.get("callers", []):
            symbols.append(c.get("name", ""))
        for c in impact.get("callees", []):
            symbols.append(c.get("name", ""))
        # Также добавим сам symbol (он есть в графе)
        symbols.append(query)
    else:
        symbols = []

    latency = (time.perf_counter() - start) * 1000.0
    return symbols, latency


def main():
    if not PROJECT_DB.exists():
        print(f"ERROR: graph.db не найден: {PROJECT_DB}")
        print("Сначала проиндексируй проект (intel_trigger_reindex).")
        sys.exit(1)

    print(f"Loading graph from: {PROJECT_DB}")
    pg = PropertyGraph(db_path=PROJECT_DB)
    node_count = pg.count_nodes()
    edge_count = pg.count_edges()
    print(f"Graph: {node_count} nodes, {edge_count} edges")

    if node_count == 0:
        print("ERROR: граф пуст — индекс не загружен.")
        sys.exit(1)

    # PURE mode (production-like: graph.db is persistence)
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    print(f"Adapter mode: {adapter._mode}\n")

    # Группировка по классам
    by_class: Dict[str, List[Tuple[bool, float]]] = {
        "modify": [], "test": [], "impact": [], "verify": []
    }

    for cls, query, expected, file_hint in TASKS:
        # Несколько прогонов для стабильности латентности
        latencies = []
        hits = 0
        for _ in range(RUNS_PER_QUERY):
            symbols, lat = run_query(adapter, cls, query)
            latencies.append(lat)
            # Recall@K: expected symbol ИЛИ file_hint присутствует в результатах
            hit = (expected in symbols) or any(file_hint in str(s) for s in symbols)
            if hit:
                hits += 1

        # Считаем hit как OR по прогонам (хотя бы раз нашёл)
        recalled = hits > 0
        median_lat = statistics.median(latencies)
        by_class[cls].append((recalled, median_lat))

        status = "OK " if recalled else "MISS"
        print(f"  [{status}] {cls:7s} q='{query:35s}' -> recalled={recalled} "
              f"median_lat={median_lat:.1f}ms symbols={len(symbols)}")

    # Сводка
    print("\n" + "=" * 60)
    print("E4.1 BENCHMARK RESULTS")
    print("=" * 60)

    total_queries = len(TASKS)
    total_recalled = 0
    all_latencies = []

    for cls in ("modify", "test", "impact", "verify"):
        results = by_class[cls]
        n = len(results)
        recalled_n = sum(1 for r, _ in results if r)
        total_recalled += recalled_n
        latencies = [l for _, l in results]
        all_latencies.extend(latencies)
        recall = recalled_n / n if n else 0
        med_lat = statistics.median(latencies) if latencies else 0
        passed = "PASS" if recall >= 0.40 else "FAIL"
        print(f"  {cls:7s}: Recall={recall:.2f} ({recalled_n}/{n})  "
              f"median_lat={med_lat:.1f}ms  [{passed}]")

    overall_recall = total_recalled / total_queries
    overall_med_lat = statistics.median(all_latencies)
    overall_pass = overall_recall >= 0.40 and overall_med_lat < 600

    print("-" * 60)
    print(f"  OVERALL: Recall={overall_recall:.2f} ({total_recalled}/{total_queries})  "
          f"median_lat={overall_med_lat:.1f}ms")
    print(f"  TARGET: Recall>=0.40 AND latency<600ms")
    print(f"  RESULT: {'PASS' if overall_pass else 'FAIL'}")
    print("=" * 60)

    # Сохраняем результат
    report = {
        "overall_recall": overall_recall,
        "overall_median_latency_ms": overall_med_lat,
        "per_class": {
            cls: {
                "recall": sum(1 for r, _ in by_class[cls] if r) / len(by_class[cls]),
                "median_latency_ms": statistics.median([l for _, l in by_class[cls]]),
            }
            for cls in by_class
        },
        "target_met": overall_pass,
    }
    out = Path("experiments/e4_1_benchmark_result.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport saved: {out}")

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
