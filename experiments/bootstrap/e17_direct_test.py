# -*- coding: utf-8 -*-
"""E17 Direct test: get_tests_for_symbol with different limits."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.artifact_paths import get_graph_db_path
from src.core.graph import PropertyGraph
from src.core.search.graph_adapter import SymbolIndexAdapter

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]


def main():
    pg = PropertyGraph(get_graph_db_path(ROOT))
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)

    # Тестовые функции с разным количеством TESTS-рёбер
    test_cases = [
        ("safe_mkdir", "src/core/artifact_paths.py"),  # 234 теста (hub)
        ("get_project_dir", "src/core/artifact_paths.py"),  # много тестов
        ("_graph_stage", "src/core/search/engine.py"),  # мало тестов
    ]

    print("=" * 80)
    print("DIRECT TEST: get_tests_for_symbol with different limits")
    print("=" * 80)

    for symbol, file_path in test_cases:
        print(f"\n[{symbol}] @ {file_path}")

        for limit in [1, 2, 3, 5, 10]:
            tests = adapter.get_tests_for_symbol(symbol, file_path, limit=limit)
            test_names = [t.symbol for t in tests[:5]]
            print(f"  limit={limit:2d}: got {len(tests):2d} tests → {test_names}")

    pg.close()


if __name__ == "__main__":
    main()
