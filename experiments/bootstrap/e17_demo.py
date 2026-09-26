# -*- coding: utf-8 -*-
"""E17 Demo: show what LLM receives WITHOUT vs WITH TESTS evidence.

Цель: показать ЦЕННОСТЬ TESTS-signal на реальном примере.
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


def demo_query(query: str):
    """Показывает что получает LLM без TESTS и с TESTS."""
    pg = PropertyGraph(get_graph_db_path(ROOT))
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    searcher = Searcher(indexer=FakeIndexer(adapter), embedder=None)

    print("=" * 80)
    print(f"QUERY: {query}")
    print("=" * 80)

    # WITHOUT TESTS
    searcher._tests_signal = False
    out_off = searcher._graph_stage(query, limit=5)

    print("\n[WITHOUT TESTS] Что получает LLM:")
    print("-" * 80)
    for i, r in enumerate(out_off[:3], 1):
        meta = r.get("metadata", {})
        print(f"{i}. {meta.get('symbol')} @ {meta.get('file')}:{meta.get('line')}")
        print(f"   score: {r.get('final_score', 0):.3f}")

    # WITH TESTS
    searcher._tests_signal = True
    out_on = searcher._graph_stage(query, limit=5)

    print("\n[WITH TESTS] Что получает LLM:")
    print("-" * 80)
    for i, r in enumerate(out_on[:5], 1):
        meta = r.get("metadata", {})
        symbol = meta.get('symbol')
        file = meta.get('file')
        line = meta.get('line')
        score = r.get('final_score', 0)
        is_test = meta.get('tests_signal', False)
        covers = meta.get('covers', '')

        if is_test:
            print(f"{i}. 🧪 TEST: {symbol}")
            print(f"   covers: {covers}")
            print(f"   file: {file}:{line}")
        else:
            print(f"{i}. 📄 FUNCTION: {symbol}")
            print(f"   file: {file}:{line}")
            print(f"   score: {score:.3f}")

    # Анализ
    tests_added = [r for r in out_on if r.get("metadata", {}).get("tests_signal")]
    print(f"\n📊 Добавлено тестов: {len(tests_added)}")
    if tests_added:
        print("   LLM теперь видит:")
        for t in tests_added[:3]:
            meta = t.get("metadata", {})
            print(f"   • {meta.get('symbol')} → проверяет {meta.get('covers')}")

    pg.close()


def main():
    print("\n" + "=" * 80)
    print("E17 DEMONSTRATION: TESTS Evidence Value")
    print("=" * 80)
    print("\nПоказываю что РЕАЛЬНО получает LLM с TESTS-signal и без него.\n")

    # Реальные запросы
    demo_query("safe_mkdir")
    print("\n\n")

    demo_query("get_project_dir")
    print("\n\n")

    demo_query("PropertyGraph")


if __name__ == "__main__":
    main()
