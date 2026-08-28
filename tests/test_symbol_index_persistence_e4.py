"""
Regression test для E4 FIX: SymbolIndex persistence (PURE vs HYBRID).

Вариант А (двухуровневая защита):
1. Explicit Guard: _mode == "pure" → skip JSON save (graph.db is truth).
2. Anti-corruption Backup: _definitions пуст И graph.count_nodes() > 0 → skip.

Тесты:
- test_pure_skip_save: PURE adapter НЕ пишет symbol_index.json
- test_hybrid_normal_save: HYBRID adapter пишет непустой symbol_index.json
- test_raw_symbol_index_save: сырой SymbolIndex пишет нормально
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.graph import PropertyGraph
from src.core.indexing.index_guard import IndexGuard
from src.core.indexing.symbol_index import SymbolIndex
from src.core.search.graph_adapter import SymbolIndexAdapter


def _make_guard_and_pg():
    tmp = Path(tempfile.mkdtemp())
    pg = PropertyGraph(db_path=tmp / "graph.db")
    guard = IndexGuard(db_path=tmp, project_path=tmp)
    return guard, pg, tmp


def test_pure_skip_save():
    """PURE adapter → save_symbol_index НЕ создаёт symbol_index.json."""
    guard, pg, tmp = _make_guard_and_pg()
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    adapter.add_definitions("src/main.py", [
        {"name": "process", "line": 10, "kind": "function"},
        {"name": "Main", "line": 20, "kind": "class"},
    ])

    result = guard.save_symbol_index(adapter)

    json_file = tmp / "symbol_index.json"
    assert result is True, "save_symbol_index должен вернуть True"
    assert not json_file.exists(), (
        f"PURE adapter НЕ должен писать JSON (graph.db is persistence), "
        f"но файл создан: {json_file}"
    )
    print(f"[PASS] test_pure_skip_save — JSON не создан, graph nodes={pg.count_nodes()}")


def test_hybrid_normal_save():
    """HYBRID adapter → save_symbol_index пишет НЕПУСТОЙ symbol_index.json."""
    guard, pg, tmp = _make_guard_and_pg()
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_HYBRID)
    adapter.add_definitions("src/main.py", [
        {"name": "process", "line": 10, "kind": "function"},
        {"name": "Main", "line": 20, "kind": "class"},
    ])

    result = guard.save_symbol_index(adapter)

    json_file = tmp / "symbol_index.json"
    assert result is True, "save_symbol_index должен вернуть True"
    assert json_file.exists(), "HYBRID adapter ДОЛЖЕН писать JSON"
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert len(data.get("definitions", {})) == 2, (
        f"HYBRID должен сохранить 2 определения, получено: {data}"
    )
    print(f"[PASS] test_hybrid_normal_save — JSON с {len(data['definitions'])} defs")


def test_raw_symbol_index_save():
    """Сырой SymbolIndex (не adapter) → пишет нормально."""
    guard, pg, tmp = _make_guard_and_pg()
    si = SymbolIndex()
    si.add_definitions("src/x.py", [{"name": "foo", "line": 1, "kind": "function"}])

    result = guard.save_symbol_index(si)

    json_file = tmp / "symbol_index.json"
    assert result is True
    assert json_file.exists(), "Raw SymbolIndex ДОЛЖЕН писать JSON"
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert len(data.get("definitions", {})) == 1, "Raw SymbolIndex должен сохранить 1 def"
    print("[PASS] test_raw_symbol_index_save — JSON с 1 def")


if __name__ == "__main__":
    test_pure_skip_save()
    test_hybrid_normal_save()
    test_raw_symbol_index_save()
    print("\nALL TESTS PASSED")
