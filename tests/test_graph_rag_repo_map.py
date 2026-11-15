"""Guard: граф знаний строится из реальной формы `get_repo_map`.

`SymbolIndex.get_repo_map()` отдаёт `symbols_by_file: {file: [ {name, kind, ...}, ... ]}`
— список СЛОВАРЕЙ, а не строк. `graph_rag.build_graph()` делал `set(symbols)` и `sym`
как ключ словаря, получал `TypeError: unhashable type: 'dict'`, ловил его общим
`except` и оставлял граф пустым. Симптом на живом сервере: `impact_analysis` →
`Symbol 'X' not found in index`, `investigate` → `abstain (0.00)` при непустом
chunks.db, в логе — `graph_rag: Failed to build graph from symbol_index`.
"""
from __future__ import annotations

from pathlib import Path

from src.core.graph_rag import GraphRAGQueryEngine


class _FakeSymbolIndex:
    """Отдаёт ту же форму, что настоящий SymbolIndex.get_repo_map()."""

    def __init__(self, mapping):
        self._mapping = mapping

    def get_repo_map(self, project_root: str):
        return {"symbols_by_file": self._mapping, "all_symbols": [], "structure": []}


def _engine(mapping) -> GraphRAGQueryEngine:
    return GraphRAGQueryEngine(Path("."), symbol_index=_FakeSymbolIndex(mapping))


DICT_SHAPE = {
    "src/app.py": [
        {"name": "build_report", "kind": "function", "definitions": [], "references": []},
        {"name": "load_data", "kind": "function", "definitions": [], "references": []},
    ],
    "src/util.py": [
        {"name": "parse_csv", "kind": "function", "definitions": [], "references": []},
    ],
}


def test_dict_shaped_symbols_are_indexed():
    graph = _engine(DICT_SHAPE).build_graph()

    assert graph["stats"]["total_files"] == 2
    assert graph["stats"]["total_symbols"] == 3
    assert graph["stats"]["total_nodes"] == 2


def test_string_shaped_symbols_still_work():
    graph = _engine({"src/a.py": ["alpha", "beta"]}).build_graph()
    assert graph["stats"]["total_symbols"] == 2


def test_one_broken_entry_does_not_zero_the_graph():
    """Один файл с мусором не должен обнулять граф целиком."""
    mapping = dict(DICT_SHAPE)
    mapping["src/broken.py"] = [None, 42, {"name": None}]
    graph = _engine(mapping).build_graph()
    assert graph["stats"]["total_files"] >= 2


def test_symbol_lookup_by_name_works_for_impact():
    engine = _engine(DICT_SHAPE)
    engine.build_graph()
    assert engine._symbol_files.get("build_report") == "src/app.py"
    assert engine._file_symbols.get("src/app.py") == {"build_report", "load_data"}


class _Ref:
    """Как SymbolRef из symbol_index: __slots__, атрибуты, не dict."""

    __slots__ = ("symbol", "file_path", "line", "kind", "is_definition")

    def __init__(self, symbol, file_path, line=1, kind="function", is_definition=True):
        self.symbol = symbol
        self.file_path = file_path
        self.line = line
        self.kind = kind
        self.is_definition = is_definition


class _RefIndex(_FakeSymbolIndex):
    def __init__(self, refs):
        super().__init__({})
        self._refs = refs

    def search_symbols(self, query):
        return self._refs


def test_feature_query_reads_symbolref_objects():
    """`search_symbols` отдаёт SymbolRef, а не dict: files не должны теряться."""
    engine = GraphRAGQueryEngine(
        Path("."), symbol_index=_RefIndex([_Ref("build_report", "src/app.py")])
    )
    result = engine.query_feature("build_report")
    assert result["files"] == ["src/app.py"]
    assert result["symbols"], "символы обязаны попасть в ответ"
