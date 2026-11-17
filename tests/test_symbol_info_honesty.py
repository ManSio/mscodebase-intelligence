"""Честность get_symbol_info: определения, счётчики вызовов, константы.

Аудит engraphis 2026-11-18 (сверка ответов по исходникам):
- `intent_recall` — «1 defs» при трёх определениях в коде;
- «3 callers» скрывало вызов из `scripts/graph_cli.py` (политика скриптов);
- `_DESTRUCTIVE_PATTERNS` (переменная) — «0 callers», хотя она используется;
- `reweight` — «10 definitions» из подстрочного поиска при нуле точных.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.core.graph import PropertyGraph
from src.core.indexing.symbol_index import SymbolRef
from src.core.search.graph_adapter import SymbolIndexAdapter
from src.mcp.tools.search_tools import GetSymbolInfoTool


def _adapter(tmp_path) -> SymbolIndexAdapter:
    pg = PropertyGraph(str(tmp_path / "t.db"))
    return SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)


def test_all_same_name_definitions_are_listed(tmp_path):
    """Три определения одного имени — три записи, первое — из src/."""
    ad = _adapter(tmp_path)
    ad.add_definitions("D:/P/experiments/shadow.py", [
        {"name": "target", "line": 10, "kind": "function_definition"},
    ])
    ad.add_definitions("D:/P/scripts/run.py", [
        {"name": "target", "line": 20, "kind": "function_definition"},
    ])
    ad.add_definitions("D:/P/src/core/mod.py", [
        {"name": "target", "line": 30, "kind": "function_definition"},
    ])

    graph = ad.build_call_graph("target")

    assert len(graph["definition"]) == 3, graph["definition"]
    assert "/src/" in graph["definition"][0]["file"], graph["definition"][0]


def test_hidden_script_callers_are_counted_not_dropped(tmp_path):
    """Вызов из scripts/ скрыт из списка, но посчитан отдельно."""
    ad = _adapter(tmp_path)
    ad.add_definitions("D:/P/src/core/mod.py", [
        {"name": "target", "line": 30, "kind": "function_definition"},
    ])
    ad.add_definitions("D:/P/src/core/user.py", [
        {"name": "prod_user", "line": 3, "kind": "function_definition"},
    ])
    ad.add_definitions("D:/P/scripts/cli.py", [
        {"name": "cli_entry", "line": 1, "kind": "function_definition"},
    ])
    ad.add_references("D:/P/src/core/user.py", [
        {"caller": "prod_user", "callee": "target", "line": 5},
    ])
    ad.add_references("D:/P/scripts/cli.py", [
        {"caller": "cli_entry", "callee": "target", "line": 7},
    ])

    graph = ad.build_call_graph("target", depth=1)

    names = {c["symbol"] for c in graph["callers"]}
    assert graph["callers_direct"] == 1, graph
    assert graph["callers_hidden_scripts"] >= 1, graph
    assert "prod_user" in names


class _FakeSI:
    """Минимальный стенд для _answer: только то, что он читает."""

    def __init__(self, definition, callers=None, hidden=0, symbols=None):
        self._graph = {
            "definition": definition,
            "callers": callers or [],
            "callees": [],
            "callers_direct": len(callers or []),
            "callers_hidden_scripts": hidden,
            "callees_direct": 0,
        }
        self._symbols = symbols or []

    def build_call_graph(self, query: str, depth: int = 2):
        return self._graph

    def search_symbols(self, query: str, top_k: int = 10):
        return self._symbols

    def get_env_accesses_for_symbol(self, query: str):
        return []


def _tool() -> GetSymbolInfoTool:
    return GetSymbolInfoTool(MagicMock())


def test_answer_says_ambiguous_for_several_definitions():
    text = _tool()._answer("target", _FakeSI([
        {"file": "a.py", "line": 1, "kind": "function_definition"},
        {"file": "b.py", "line": 2, "kind": "function_definition"},
    ]))
    assert "AMBIGUOUS: 2 definitions" in text


def test_variable_does_not_claim_zero_callers():
    text = _tool()._answer("_PATTERNS", _FakeSI([
        {"file": "mcp_server.py", "line": 2384, "kind": "variable"},
    ]))
    assert "граф вызовов не применим" in text
    assert "0 callers" not in text


def test_hidden_scripts_are_named_in_the_answer():
    text = _tool()._answer("target", _FakeSI(
        [{"file": "a.py", "line": 1, "kind": "function_definition"}],
        callers=[{"symbol": "prod", "file": "u.py", "line": 3, "depth": 1}],
        hidden=2,
    ))
    assert "скрыто" in text and "2" in text


def test_substring_matches_are_not_called_definitions():
    si = _FakeSI([], symbols=[
        SymbolRef(symbol="reweight_memory", file_path="x.py", line=5,
                  kind="function_definition", is_definition=True),
    ])
    text = _tool()._answer("reweight", si)
    assert "точного символа нет" in text
    assert "похожие имена" in text
    assert "definitions" not in text
