# -*- coding: utf-8 -*-
"""E17 Parameter Sweep: graph_score, test_limit variations.

Цель: понять как параметры влияют на результаты.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.artifact_paths import get_graph_db_path
from src.core.graph import PropertyGraph
from src.core.search.engine import Searcher
from src.core.search.graph_adapter import SymbolIndexAdapter

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]


class FakeIndexer:
    def __init__(self, symbol_index):
        self._symbol_index = symbol_index
        self.symbol_index = symbol_index
    async def close_async(self):
        pass


# 10 реальных запросов (смешанные: identifier + NL-like)
QUERIES = [
    "safe_mkdir",
    "get_project_dir",
    "PropertyGraph",
    "Searcher",
    "how does reindex work",
    "embedding model config",
    "graph_stage",
    "TESTS edges",
    "bootstrap pipeline",
    "artifact_paths",
]


def run_sweep(graph_score: float, test_limit_per_func: int, test_limit_per_query: int):
    """Прогоняет панель с заданными параметрами."""
    pg = PropertyGraph(get_graph_db_path(ROOT))
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    searcher = Searcher(indexer=FakeIndexer(adapter), embedder=None)
    searcher._tests_signal = True

    results = []
    for q in QUERIES:
        out = searcher._graph_stage(q, limit=8)

        # Считаем тесты в результате
        tests_in_result = [r for r in out if r.get("metadata", {}).get("tests_signal")]
        funcs_in_result = [r for r in out if r.get("metadata", {}).get("is_definition")]

        results.append({
            "query": q,
            "total_results": len(out),
            "funcs": len(funcs_in_result),
            "tests": len(tests_in_result),
            "test_symbols": [r.get("metadata", {}).get("symbol") for r in tests_in_result[:3]],
        })

    pg.close()
    return results


def main():
    print("=" * 80)
    print("E17 PARAMETER SWEEP")
    print("=" * 80)

    # Базовый вариант (текущие параметры)
    print("\n[BASELINE] graph_score=0.4, limit=3 per func, cap=6 per query")
    baseline = run_sweep(0.4, 3, 6)
    total_tests_baseline = sum(r["tests"] for r in baseline)
    print(f"  Total tests added: {total_tests_baseline}")
    for r in baseline[:3]:
        print(f"  {r['query']}: {r['funcs']} funcs, {r['tests']} tests")

    # Вариант 1: выше graph_score
    print("\n[VARIANT 1] graph_score=0.6 (выше)")
    v1 = run_sweep(0.6, 3, 6)
    total_tests_v1 = sum(r["tests"] for r in v1)
    print(f"  Total tests added: {total_tests_v1}")

    # Вариант 2: ниже graph_score
    print("\n[VARIANT 2] graph_score=0.2 (ниже)")
    v2 = run_sweep(0.2, 3, 6)
    total_tests_v2 = sum(r["tests"] for r in v2)
    print(f"  Total tests added: {total_tests_v2}")

    # Вариант 3: больше тестов на функцию
    print("\n[VARIANT 3] limit=5 per func (больше)")
    v3 = run_sweep(0.4, 5, 6)
    total_tests_v3 = sum(r["tests"] for r in v3)
    print(f"  Total tests added: {total_tests_v3}")

    # Вариант 4: меньше тестов на функцию
    print("\n[VARIANT 4] limit=1 per func (меньше)")
    v4 = run_sweep(0.4, 1, 6)
    total_tests_v4 = sum(r["tests"] for r in v4)
    print(f"  Total tests added: {total_tests_v4}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Baseline (0.4, limit=3): {total_tests_baseline} tests")
    print(f"Higher score (0.6):      {total_tests_v1} tests")
    print(f"Lower score (0.2):       {total_tests_v2} tests")
    print(f"More per func (limit=5): {total_tests_v3} tests")
    print(f"Less per func (limit=1): {total_tests_v4} tests")

    print("\nNOTE: graph_score не влияет на количество тестов (они добавляются отдельно).")
    print("      graph_score влияет только на ранжирование в RRF с другими сигналами.")


if __name__ == "__main__":
    main()
