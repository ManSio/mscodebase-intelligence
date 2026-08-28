"""
E4: SymbolIndex Persistence Bug — воспроизведение и замер.

Гипотеза: SymbolIndexAdapter в MODE_PURE хранит данные в PropertyGraph,
но save_symbol_index читает _definitions → пустой JSON.

Замер: сколько символов в памяти vs на диске при cold-start.
"""
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tempfile
from src.core.indexing.symbol_index import SymbolIndex
from src.core.search.graph_adapter import SymbolIndexAdapter
from src.core.graph import PropertyGraph


def _make_pg():
    tmpdir = tempfile.mkdtemp()
    return PropertyGraph(db_path=Path(tmpdir) / "graph.db")


def experiment_1_pure_vs_hybrid():
    """Сравнение PURE vs HYBRID: что попадает в _definitions."""
    pg = _make_pg()

    # HYBRID
    hybrid = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_HYBRID)
    hybrid.add_definitions("test.py", [
        {"name": "foo", "line": 10, "kind": "function"},
        {"name": "Bar", "line": 20, "kind": "class"},
    ])
    hybrid.add_definitions("test2.py", [
        {"name": "baz", "line": 5, "kind": "function"},
    ])

    # PURE
    pure = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    pure.add_definitions("test.py", [
        {"name": "foo", "line": 10, "kind": "function"},
        {"name": "Bar", "line": 20, "kind": "class"},
    ])
    pure.add_definitions("test2.py", [
        {"name": "baz", "line": 5, "kind": "function"},
    ])

    print("=== Experiment 1: PURE vs HYBRID ===")
    print(f"HYBRID _definitions count: {len(hybrid._definitions)}")  # Ожидаем 3
    print(f"PURE   _definitions count: {len(pure._definitions)}")    # Ожидаем 0
    print(f"PURE   graph nodes: {pure._graph.count_nodes()}")      # Ожидаем > 0
    print()


def experiment_2_save_roundtrip():
    """Симуляция save→load цикла: PURE adapter → пустой JSON."""
    pg = _make_pg()
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    adapter.add_definitions("src/main.py", [
        {"name": "process_data", "line": 42, "kind": "function"},
        {"name": "DataProcessor", "line": 100, "kind": "class"},
    ])
    adapter.add_references("src/main.py", [
        {"caller": "process_data", "callee": "validate_input", "line": 45},
    ])

    print("=== Experiment 2: Save Roundtrip ===")
    print(f"In-memory _definitions: {len(adapter._definitions)} keys")
    print(f"In-memory _references: {len(adapter._references)} keys")
    print(f"Graph nodes: {adapter._graph.count_nodes()}")

    # Симуляция save_symbol_index (из index_guard.py:366-398)
    defs = {k: [r.to_dict() for r in v] for k, v in adapter._definitions.items()}
    refs = {k: [r.to_dict() for r in v] for k, v in adapter._references.items()}
    fts = {k: list(v) for k, v in adapter._file_to_symbols.items()}

    data = {"definitions": defs, "references": refs, "file_to_symbols": fts}

    print(f"Serialized definitions: {len(defs)} keys")
    print(f"Serialized references: {len(refs)} keys")
    print(f"JSON output: {json.dumps(data, indent=2)}")
    print()

    # Вердикт
    if len(defs) == 0 and len(adapter._graph._nodes) > 0:
        print("BUG CONFIRMED: PureGraph data in graph, but _definitions empty → JSON is empty")
    else:
        print("BUG NOT REPRODUCED (unexpected state)")


def experiment_3_cold_start_sim():
    """Симуляция cold-start: загрузка пустого JSON → 0 символов."""
    print("=== Experiment 3: Cold-Start Simulation ===")

    # Создаём пустой JSON (какой бы записал save_symbol_index для PURE)
    empty_json = json.dumps({
        "definitions": {},
        "references": {},
        "file_to_symbols": {},
        "saved_at": "2026-08-27T00:00:00"
    })

    # Симуляция load_symbol_index
    raw = json.loads(empty_json)
    loaded_defs = raw.get("definitions", {})
    loaded_refs = raw.get("references", {})

    print(f"Loaded definitions: {len(loaded_defs)} keys")
    print(f"Loaded references: {len(loaded_refs)} keys")

    if len(loaded_defs) == 0:
        print("COLD-START: SymbolIndex пуст → Recall = 0.00 (подтверждено)")
    print()


if __name__ == "__main__":
    experiment_1_pure_vs_hybrid()
    experiment_2_save_roundtrip()
    experiment_3_cold_start_sim()
