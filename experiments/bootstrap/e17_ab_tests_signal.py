# -*- coding: utf-8 -*-
"""E17 A/B: TESTS-сигнал в graph-stage — контроль (off) vs лечение (on).

Воспроизводимый замер: реальный Searcher._graph_stage на live PropertyGraph
(get_graph_db_path проектного корня), golden-набор из 7 функций с
верифицированными тестами-покрытия (trace_result.json, 1727 тестов).

Read-only: PropertyGraph открывается только на чтение, запись в граф не ведётся.
Run:
    cd D:\\Project\\MSCodeBase
    python -X utf8 experiments/bootstrap/e17_ab_tests_signal.py
"""
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

# Golden: функция, которую ищем идентификатором, и её файл.
# Тесты-покрытия для каждой функции верифицированы в e17_golden.json
# (построен из trace_result.json + live графа).
QUERIES = [
    {"q": "safe_mkdir", "symbol": "safe_mkdir", "file": "src/core/artifact_paths.py"},
    {"q": "shortest_path", "symbol": "shortest_path", "file": "src/core/graph.py"},
    {"q": "get_neighbors", "symbol": "get_neighbors", "file": "src/core/graph.py"},
    {"q": "reciprocal_rank_fusion_3way", "symbol": "reciprocal_rank_fusion_3way", "file": "src/core/search/scoring.py"},
    {"q": "switch_db", "symbol": "switch_db", "file": "src/core/indexing/db_manager.py"},
    {"q": "calculate_token_savings", "symbol": "calculate_token_savings", "file": "src/core/search/token_savings.py"},
    {"q": "_graph_stage", "symbol": "_graph_stage", "file": "src/core/search/engine.py"},
]


class FakeIndexer:
    """Минимальный indexer-контракт Searcher'а: только symbol_index."""

    def __init__(self, symbol_index):
        self._symbol_index = symbol_index
        self.symbol_index = symbol_index

    async def close_async(self):
        pass


def measure(searcher: Searcher, flag_on: bool) -> list:
    searcher._tests_signal = flag_on
    rows = []
    for item in QUERIES:
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
        rows.append({"q": item["q"], "dt_ms": dt, "top6": top6})
    return rows


def main() -> int:
    pg = PropertyGraph(get_graph_db_path(ROOT))
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    searcher = Searcher(indexer=FakeIndexer(adapter), embedder=None)

    res_off = measure(searcher, flag_on=False)
    res_on = measure(searcher, flag_on=True)

    hits_off = {"h1": 0, "h3": 0, "n": len(QUERIES)}
    hits_on = {"h1": 0, "h3": 0, "n": len(QUERIES)}
    mrr_num_off = 0.0
    mrr_num_on = 0.0
    signaled = []

    print("=== E17 A/B: graph_stage — контроль (OFF) vs лечение (ON) ===", flush=True)
    for off, on, item in zip(res_off, res_on, QUERIES):
        target = f"{item['file']}:{item['symbol']}"
        off_rank = next(
            (i + 1 for i, r in enumerate(off["top6"]) if item["symbol"] in r and item["file"] in r),
            None,
        )
        on_rank = next(
            (i + 1 for i, r in enumerate(on["top6"]) if item["symbol"] in r and item["file"] in r),
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
        print(
            f"[{item['q']}] target={target} | rank off={off_rank} on={on_rank} | "
            f"NEW tests in ON: {new_tests or 'none'}",
            flush=True,
        )

    print("=" * 60, flush=True)
    print(f"hit@1 off={hits_off['h1']}/{hits_off['n']} on={hits_on['h1']}/{hits_on['n']}", flush=True)
    print(f"hit@3 off={hits_off['h3']}/{hits_off['n']} on={hits_on['h3']}/{hits_on['n']}", flush=True)
    n_with_new = sum(1 for _, nt in signaled if nt)
    print(f"TESTS-signal: {n_with_new}/{len(signaled)} queries получили новые покрывающие тесты", flush=True)
    print(
        f"MRR(function) off={mrr_num_off / len(QUERIES):.3f} "
        f"on={mrr_num_on / len(QUERIES):.3f}",
        flush=True,
    )
    avg_off = sum(r["dt_ms"] for r in res_off) / len(res_off)
    avg_on = sum(r["dt_ms"] for r in res_on) / len(res_on)
    print(
        f"graph_stage avg dt: off={avg_off:.2f}ms on={avg_on:.2f}ms "
        f"(overhead {(avg_on / avg_off - 1) * 100:+.1f}%)",
        flush=True,
    )

    print("=" * 60, flush=True)
    print("RETRACTION CHECK (лечение, файлы на диске):", flush=True)
    missing = 0
    for on in res_on:
        for r in on["top6"]:
            parts = r.replace(" [T]", "").split(":")
            if len(parts) < 2:
                continue
            rel = parts[0]
            if not (ROOT / rel).exists():
                missing += 1
                print(f"  MISSING FILE: {rel}", flush=True)
    print(f"  missing files: {missing}" if missing else "  all referenced files exist on disk", flush=True)

    pg.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
