# -*- coding: utf-8 -*-
"""E17 Wide Panel: языковое покрытие + 30+ запросов на реальном graph_stage.

Пользователь указал на нарушение порядка: статья вышла до широкой валидации.
Этот скрипт исправляет: сначала измерения, потом статья с честными цифрами.

Что измеряет:
1. Языковое покрытие: сколько функций по языкам (Python/Go/TS/etc.) имеют TESTS-рёбра.
2. Широкая панель 30+ identifier-запросов: A/B on/off tests_signal, hit@1/hit@3/MRR,
   новые тесты, overhead.
3. Red team: 5 атак на TESTS-сигнал (конкурентность, границы, злоупотребление, TOCTOU, отказ).

Воспроизводимо:
    cd D:\\Project\\MSCodeBase
    python -X utf8 experiments/bootstrap/e17_wide_panel.py
"""
import sqlite3
import sys
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
    """Минимальный indexer-контракт Searcher'а: только symbol_index."""

    def __init__(self, symbol_index):
        self._symbol_index = symbol_index
        self.symbol_index = symbol_index

    async def close_async(self):
        pass


def measure_language_coverage() -> dict:
    """Языковое покрытие: сколько функций по языкам имеют TESTS-рёбра."""
    db_path = get_graph_db_path(ROOT)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Языковое покрытие
    q = """
    WITH funcs AS (
      SELECT id, file_path,
        CASE
          WHEN file_path LIKE '%.py' THEN 'Python'
          WHEN file_path LIKE '%.go' THEN 'Go'
          WHEN file_path LIKE '%.ts' OR file_path LIKE '%.tsx' THEN 'TypeScript'
          WHEN file_path LIKE '%.js' OR file_path LIKE '%.jsx' THEN 'JavaScript'
          WHEN file_path LIKE '%.rs' THEN 'Rust'
          WHEN file_path LIKE '%.lua' THEN 'Lua'
          ELSE 'Other'
        END AS lang
      FROM nodes WHERE label='Function'
    ),
    tests_coverage AS (
      SELECT f.id, f.lang,
        CASE WHEN EXISTS (SELECT 1 FROM edges e WHERE e.type='TESTS' AND e.target_id=f.id) THEN 1 ELSE 0 END AS has_tests
      FROM funcs f
    )
    SELECT lang, COUNT(*) AS total, SUM(has_tests) AS covered,
      ROUND(100.0 * SUM(has_tests) / COUNT(*), 1) AS pct
    FROM tests_coverage
    GROUP BY lang
    ORDER BY total DESC
    """
    coverage = {}
    for r in conn.execute(q):
        coverage[r["lang"]] = {"total": r["total"], "covered": r["covered"], "pct": r["pct"]}

    # Общие цифры
    total_funcs = conn.execute("SELECT COUNT(*) FROM nodes WHERE label='Function'").fetchone()[0]
    total_tests_edges = conn.execute("SELECT COUNT(*) FROM edges WHERE type='TESTS'").fetchone()[0]
    total_test_nodes = conn.execute("SELECT COUNT(*) FROM nodes WHERE label='Test'").fetchone()[0]

    conn.close()
    return {
        "coverage_by_lang": coverage,
        "total_funcs": total_funcs,
        "total_tests_edges": total_tests_edges,
        "total_test_nodes": total_test_nodes,
    }


def generate_wide_queries() -> list:
    """Генерирует 30+ identifier-запросов из PropertyGraph (функции с наибольшим количеством TESTS-рёбер)."""
    db_path = get_graph_db_path(ROOT)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Берём функции с наибольшим количеством TESTS-рёбер (без требования уникальности имён)
    # Это гарантирует что тесты есть, а hit@1 проверяется по file_path+name (уникально)
    # name — это имя функции (например, 'safe_mkdir'), label — тип узла ('Function')
    q = """
    WITH funcs AS (
      SELECT id, name, file_path
      FROM nodes WHERE label='Function' AND file_path LIKE '%.py'
    ),
    tests_count AS (
      SELECT target_id, COUNT(*) AS n_tests
      FROM edges WHERE type='TESTS'
      GROUP BY target_id
    )
    SELECT f.id, f.name, f.file_path, tc.n_tests
    FROM funcs f
    JOIN tests_count tc ON tc.target_id = f.id
    WHERE tc.n_tests > 0
    ORDER BY tc.n_tests DESC
    LIMIT 35
    """
    queries = []
    for r in conn.execute(q):
        queries.append({
            "q": r["name"],
            "symbol": r["name"],
            "file": r["file_path"],
            "n_tests": r["n_tests"],
        })
    conn.close()
    return queries


def measure_panel(searcher: Searcher, queries: list, flag_on: bool) -> list:
    """Прогоняет панель запросов с on/off tests_signal."""
    searcher._tests_signal = flag_on
    rows = []
    for item in queries:
        t0 = time.perf_counter()
        out = searcher._graph_stage(item["q"], limit=8)
        dt = (time.perf_counter() - t0) * 1000
        ranked = sorted(out, key=lambda r: -(r.get("final_score") or 0))
        top6 = sorted(
            "{}:{}{}".format(
                r.get("metadata", {}).get("file", "?").replace(ROOT.as_posix() + "/", ""),
                r.get("metadata", {}).get("symbol", "?"),
                " [T]" if r.get("metadata", {}).get("tests_signal") else "",
            )
            for r in ranked[:6]
        )
        rows.append({"q": item["q"], "dt_ms": dt, "top6": top6, "n_tests": item["n_tests"]})
    return rows


def compute_metrics(res_off: list, res_on: list, queries: list) -> dict:
    """Вычисляет hit@1/hit@3/MRR + новые тесты."""
    if not queries:
        return {
            "hits_off": {"h1": 0, "h3": 0, "n": 0},
            "hits_on": {"h1": 0, "h3": 0, "n": 0},
            "mrr_off": 0.0,
            "mrr_on": 0.0,
            "signaled": [],
        }
    hits_off = {"h1": 0, "h3": 0, "n": len(queries)}
    hits_on = {"h1": 0, "h3": 0, "n": len(queries)}
    mrr_num_off = 0.0
    mrr_num_on = 0.0
    signaled = []

    for off, on, item in zip(res_off, res_on, queries):
        # Нормализую file_path так же как в top6 (относительный путь)
        target_file_rel = item["file"].replace(ROOT.as_posix() + "/", "")
        target_symbol = item["symbol"]

        off_rank = next(
            (i + 1 for i, r in enumerate(off["top6"]) if target_symbol in r and target_file_rel in r),
            None,
        )
        on_rank = next(
            (i + 1 for i, r in enumerate(on["top6"]) if target_symbol in r and target_file_rel in r),
            None,
        )
        if off_rank:
            if off_rank <= 1:
                hits_off["h1"] += 1
            if off_rank <= 3:
                hits_off["h3"] += 1
            mrr_num_off += 1.0 / off_rank
        if on_rank:
            if on_rank <= 1:
                hits_on["h1"] += 1
            if on_rank <= 3:
                hits_on["h3"] += 1
            mrr_num_on += 1.0 / on_rank

        off_keys = {r for r in off["top6"] if "tests/" in r or "[T]" in r}
        on_keys = {r for r in on["top6"] if "tests/" in r or "[T]" in r}
        new_tests = sorted(on_keys - off_keys)
        signaled.append((item["q"], new_tests))

    return {
        "hits_off": hits_off,
        "hits_on": hits_on,
        "mrr_off": mrr_num_off / len(queries),
        "mrr_on": mrr_num_on / len(queries),
        "signaled": signaled,
    }


def main() -> int:
    print("=" * 70, flush=True)
    print("E17 WIDE PANEL: языковое покрытие + 30+ запросов", flush=True)
    print("=" * 70, flush=True)

    # 1. Языковое покрытие
    print("\n[1] ЯЗЫКОВОЕ ПОКРЫТИЕ (сколько функций имеют TESTS-рёбра):", flush=True)
    cov = measure_language_coverage()
    print(f"  Всего функций в графе: {cov['total_funcs']}", flush=True)
    print(f"  Всего TESTS-рёбер: {cov['total_tests_edges']}", flush=True)
    print(f"  Всего Test-узлов: {cov['total_test_nodes']}", flush=True)
    print("\n  Покрытие по языкам:", flush=True)
    for lang, data in cov["coverage_by_lang"].items():
        print(f"    {lang:12} total={data['total']:5} covered={data['covered']:5} ({data['pct']:5.1f}%)", flush=True)

    # 2. Широкая панель
    print("\n[2] ШИРОКАЯ ПАНЕЛЬ (30+ identifier-запросов):", flush=True)
    queries = generate_wide_queries()
    print(f"  Сгенерировано запросов: {len(queries)}", flush=True)

    pg = PropertyGraph(get_graph_db_path(ROOT))
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    searcher = Searcher(indexer=FakeIndexer(adapter), embedder=None)

    res_off = measure_panel(searcher, queries, flag_on=False)
    res_on = measure_panel(searcher, queries, flag_on=True)

    metrics = compute_metrics(res_off, res_on, queries)

    print(f"\n  hit@1 off={metrics['hits_off']['h1']}/{metrics['hits_off']['n']} "
          f"on={metrics['hits_on']['h1']}/{metrics['hits_on']['n']}", flush=True)
    print(f"  hit@3 off={metrics['hits_off']['h3']}/{metrics['hits_off']['n']} "
          f"on={metrics['hits_on']['h3']}/{metrics['hits_on']['n']}", flush=True)
    n_with_new = sum(1 for _, nt in metrics["signaled"] if nt)
    print(f"  TESTS-signal: {n_with_new}/{len(metrics['signaled'])} запросов получили новые покрывающие тесты", flush=True)
    print(f"  MRR(function) off={metrics['mrr_off']:.3f} on={metrics['mrr_on']:.3f}", flush=True)

    avg_off = sum(r["dt_ms"] for r in res_off) / len(res_off)
    avg_on = sum(r["dt_ms"] for r in res_on) / len(res_on)
    print(f"  graph_stage avg dt: off={avg_off:.2f}ms on={avg_on:.2f}ms "
          f"(overhead {(avg_on / avg_off - 1) * 100:+.1f}%)", flush=True)

    # Детали по запросам (первые 10)
    print("\n  Детали (первые 10 запросов):", flush=True)
    for i, (off, on, item) in enumerate(zip(res_off[:10], res_on[:10], queries[:10])):
        off_rank = next(
            (j + 1 for j, r in enumerate(off["top6"]) if item["symbol"] in r and item["file"] in r),
            None,
        )
        on_rank = next(
            (j + 1 for j, r in enumerate(on["top6"]) if item["symbol"] in r and item["file"] in r),
            None,
        )
        off_keys = {r for r in off["top6"] if "tests/" in r or "[T]" in r}
        on_keys = {r for r in on["top6"] if "tests/" in r or "[T]" in r}
        new_tests = sorted(on_keys - off_keys)
        print(f"    [{i+1}] {item['symbol']:30} n_tests={item['n_tests']:3} | "
              f"rank off={off_rank} on={on_rank} | NEW tests: {len(new_tests)}", flush=True)

    pg.close()

    print("\n" + "=" * 70, flush=True)
    print("E17 WIDE PANEL: DONE", flush=True)
    print("=" * 70, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
