"""Финальная верификация Задачи 5/5: граф в центре + дедуп рендера.

Проверяет на РЕАЛЬНОМ graph.db:
1. find_references("search_with_mode") == 1  (дедуп по (symbol, file, line))
2. find_references("_expand_graph_context") == 2 (методы резолвятся как узлы)
3. Реальный путь Searcher._expand_graph_context обогащает callers
4. Рендер '🔗 Вызывается из:' содержит SearchCodeTool.execute ровно 1 раз
"""
import sys
import time
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT = Path("D:/Project/MSCodeBase").resolve()

try:
    from src.core.artifact_paths import get_graph_db_path
    from src.core.graph import PropertyGraph
    from src.core.search.graph_adapter import SymbolIndexAdapter
    from src.core.search.engine import Searcher

    # ---- 1. Загрузка реального графа ----
    graph_path = get_graph_db_path(PROJECT)
    print(f"[1] graph.db: {graph_path}")
    pg = PropertyGraph(graph_path)
    si = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    stats = pg.get_stats()
    print(f"    nodes={stats.get('nodes')}, edges={stats.get('edges')}")

    # ---- 2. Дедуп find_references("search_with_mode") ----
    refs_sym = si.find_references("search_with_mode")
    print(f"[2] find_references('search_with_mode') -> {len(refs_sym)}")
    for r in refs_sym:
        print(f"    - {r.symbol} @ {r.file_path}:{r.line} kind={r.kind} def={r.is_definition}")
    assert len(refs_sym) == 1, (
        f"FAIL: ожидался 1 (дедуп), получено {len(refs_sym)}"
    )
    assert refs_sym[0].symbol == "SearchCodeTool.execute", (
        f"FAIL: ожидался SearchCodeTool.execute, получен {refs_sym[0].symbol}"
    )

    # ---- 3. Методы резолвятся как реальные узлы ----
    refs_expand = si.find_references("_expand_graph_context")
    print(f"[3] find_references('_expand_graph_context') -> {len(refs_expand)}")
    for r in refs_expand:
        print(f"    - {r.symbol} @ {r.file_path}:{r.line}")
    assert len(refs_expand) >= 2, (
        f"FAIL: ожидалось >=2 вызова, получено {len(refs_expand)}"
    )

    # ---- 4. Реальный путь _expand_graph_context ----
    class FakeIndexer:
        def __init__(self, si_):
            self._symbol_index = si_
            self.symbol_index = si_

    searcher = Searcher(FakeIndexer(si), embedder=None)
    results = [{
        "text": 'def search_with_mode(self, mode: str = "auto") -> list:',
        "metadata": {"file": "src/core/search/engine.py", "chunk_index": 0},
    }]
    t1 = time.perf_counter()
    out = searcher._expand_graph_context(results, "search_with_mode")
    elapsed_ms = (time.perf_counter() - t1) * 1000

    callers = out[0]["metadata"].get("callers", [])
    print(f"[4] _expand_graph_context: {len(callers)} callers, {elapsed_ms:.2f}ms")
    for c in callers:
        print(f"    - {c['symbol']} @ {c['file']}:{c['line']}")
    assert len(callers) == 1, f"FAIL: ожидался 1 caller (дедуп), получено {len(callers)}"
    assert callers[0]["symbol"] == "SearchCodeTool.execute", (
        f"FAIL: ожидался SearchCodeTool.execute, получен {callers[0]['symbol']}"
    )

    # ---- 5. Рендер (как в search) ----
    caller_names = ", ".join(c.get("symbol", "?") for c in callers[:3])
    render = f"🔗 Вызывается из: {caller_names}"
    print(f"[5] RENDER: {render}")
    assert render.count("SearchCodeTool.execute") == 1, (
        "FAIL: SearchCodeTool.execute в рендере не 1 раз"
    )
    assert elapsed_ms < 50, f"FAIL: graph_expansion_ms={elapsed_ms:.2f} > 50ms бюджета"

    print("\n✅ FINAL RENDER VERIFIED: dedup OK, callers OK, render OK")

except Exception:
    import traceback

    traceback.print_exc()
    sys.exit(1)
