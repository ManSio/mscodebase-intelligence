# -*- coding: utf-8 -*-
"""E17 Red Team: 5 атак на TESTS-сигнал.

Атаки:
1. Конкурентность: 10 потоков одновременно вызывают _graph_stage — нет ли гонки?
2. Границы: функция с 1000 тестами — сколько времени занимает get_tests_for_symbol?
3. Злоупотребление: запрос несуществующей функции — graceful degradation?
4. TOCTOU: между find_nodes и get_neighbors граф меняется — как обрабатывается?
5. Отказ зависимостей: PropertyGraph закрыт/повреждён — graceful degradation?

Воспроизводимо:
    cd D:\\Project\\MSCodeBase
    python -X utf8 experiments/bootstrap/e17_redteam.py
"""
import sys
import threading
import time
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


def attack_1_concurrency():
    """Атака 1: Конкурентность — 10 потоков одновременно вызывают _graph_stage."""
    print("\n[АТАКА 1] Конкурентность: 10 потоков × 100 вызовов", flush=True)
    pg = PropertyGraph(get_graph_db_path(ROOT))
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    searcher = Searcher(indexer=FakeIndexer(adapter), embedder=None)
    searcher._tests_signal = True

    errors = []
    lock = threading.Lock()

    def worker():
        try:
            for _ in range(100):
                searcher._graph_stage('safe_mkdir', limit=8)
        except Exception as e:  # noqa: BLE001 — red team: собираем все ошибки конкурентности
            with lock:
                errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    dt = (time.perf_counter() - t0) * 1000

    print(f"  1000 вызовов за {dt:.1f}ms ({dt/1000:.2f}ms/вызов)", flush=True)
    print(f"  Ошибок: {len(errors)}", flush=True)
    if errors:
        print(f"  Первая ошибка: {errors[0]}", flush=True)
    pg.close()
    return len(errors) == 0


def attack_2_boundaries():
    """Атака 2: Границы — функция с наибольшим количеством тестов."""
    print("\n[АТАКА 2] Границы: функция с наибольшим количеством тестов", flush=True)
    pg = PropertyGraph(get_graph_db_path(ROOT))
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    searcher = Searcher(indexer=FakeIndexer(adapter), embedder=None)
    searcher._tests_signal = True

    # safe_mkdir имеет 234 теста (из e17_wide_panel)
    t0 = time.perf_counter()
    out = searcher._graph_stage('safe_mkdir', limit=8)
    dt = (time.perf_counter() - t0) * 1000

    # сколько тестов добавлено
    tests_added = sum(1 for r in out if r.get('metadata', {}).get('tests_signal'))
    print(f"  Время: {dt:.2f}ms", flush=True)
    print(f"  Тестов добавлено: {tests_added}", flush=True)
    print(f"  Всего результатов: {len(out)}", flush=True)
    pg.close()
    return dt < 100  # приемлемо если <100ms


def attack_3_abuse():
    """Атака 3: Злоупотребление — запрос несуществующей функции."""
    print("\n[АТАКА 3] Злоупотребление: запрос несуществующей функции", flush=True)
    pg = PropertyGraph(get_graph_db_path(ROOT))
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    searcher = Searcher(indexer=FakeIndexer(adapter), embedder=None)
    searcher._tests_signal = True

    try:
        out = searcher._graph_stage('nonexistent_function_xyz_12345', limit=8)
        print(f"  Результатов: {len(out)}", flush=True)
        print(f"  Graceful degradation: OK (вернул {len(out)} результатов)", flush=True)
        pg.close()
        return True
    except Exception as e:  # noqa: BLE001 — red team: проверяем graceful degradation
        print(f"  Ошибка: {e}", flush=True)
        pg.close()
        return False


def attack_4_toctou():
    """Атака 4: TOCTOU — граф меняется между вызовами (имитация reindex)."""
    print("\n[АТАКА 4] TOCTOU: граф закрывается между вызовами", flush=True)
    pg = PropertyGraph(get_graph_db_path(ROOT))
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    searcher = Searcher(indexer=FakeIndexer(adapter), embedder=None)
    searcher._tests_signal = True

    # первый вызов
    searcher._graph_stage('safe_mkdir', limit=8)

    # имитация reindex: закрываем граф
    pg.close()

    # второй вызов (граф закрыт)
    try:
        out2 = searcher._graph_stage('safe_mkdir', limit=8)
        print(f"  После закрытия графа: {len(out2)} результатов", flush=True)
        print("  Graceful degradation: OK", flush=True)
        return True
    except Exception as e:  # noqa: BLE001 — red team: проверяем TOCTOU
        print(f"  Ошибка после закрытия: {e}", flush=True)
        print("  Graceful degradation: FAIL", flush=True)
        return False


def attack_5_dependency_failure():
    """Атака 5: Отказ зависимостей — PropertyGraph повреждён."""
    print("\n[АТАКА 5] Отказ зависимостей: PropertyGraph с несуществующим путём", flush=True)
    try:
        pg = PropertyGraph(Path('Z:/nonexistent/graph.db'))
        adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
        searcher = Searcher(indexer=FakeIndexer(adapter), embedder=None)
        searcher._tests_signal = True

        out = searcher._graph_stage('safe_mkdir', limit=8)
        print(f"  Результатов: {len(out)}", flush=True)
        print("  Graceful degradation: OK", flush=True)
        return True
    except Exception as e:  # noqa: BLE001 — red team: проверяем отказ зависимостей
        print(f"  Ошибка: {e}", flush=True)
        print("  Graceful degradation: FAIL", flush=True)
        return False


def main() -> int:
    print("=" * 70, flush=True)
    print("E17 RED TEAM: 5 атак на TESTS-сигнал", flush=True)
    print("=" * 70, flush=True)

    results = []
    results.append(("Конкурентность", attack_1_concurrency()))
    results.append(("Границы", attack_2_boundaries()))
    results.append(("Злоупотребление", attack_3_abuse()))
    results.append(("TOCTOU", attack_4_toctou()))
    results.append(("Отказ зависимостей", attack_5_dependency_failure()))

    print("\n" + "=" * 70, flush=True)
    print("РЕЗУЛЬТАТЫ RED TEAM:", flush=True)
    print("=" * 70, flush=True)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} {name}", flush=True)

    all_passed = all(passed for _, passed in results)
    print(f"\nИтого: {sum(1 for _, p in results if p)}/{len(results)} атак отражено", flush=True)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
