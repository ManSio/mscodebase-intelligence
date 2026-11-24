"""Guard: graph_query понимает find_definition (замер 2026-11-16).

Живой вызов `graph_query(query_type="find_definition", name=...)` возвращал
`INTERNAL_ERROR: Unknown query_type`, хотя символьный индекс умеет искать
определения нативно — агент уходил в обходные инструменты.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.mcp.tools.graph_tools import GraphQueryTool


class _Ref:
    """Как SymbolRef из symbol_index."""

    __slots__ = ("symbol", "file_path", "line", "kind", "is_definition")

    def __init__(self, symbol, file_path, line=10, kind="function", is_definition=True):
        self.symbol = symbol
        self.file_path = file_path
        self.line = line
        self.kind = kind
        self.is_definition = is_definition

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "file": self.file_path,
            "line": self.line,
            "kind": self.kind,
            "is_def": self.is_definition,
        }


class _SymbolIndex:
    def __init__(self, refs):
        self.refs = refs
        self.asked: list[str] = []

    def find_definitions(self, symbol):
        self.asked.append(symbol)
        return self.refs


class _Tool:
    """GraphQueryTool без DI: подменяем только resolve_* точки."""

    def __init__(self, index):
        self._index = index

    def resolve_indexer(self, explicit_project_root=None):
        class _Indexer:
            project_path = Path(".")

        return _Indexer()

    def resolve_symbol_index(self, explicit_project_root=None):
        return self._index


def _query(index, query_type: str, target: str = "as_dict") -> dict:
    tool = _Tool(index)
    raw = asyncio.run(
        GraphQueryTool._execute_query(tool, query_type, target, {}, project_root="")
    )
    return json.loads(raw) if isinstance(raw, str) else raw


@pytest.mark.parametrize(
    "query_type", ["find_definition", "definition", "find_definitions", "find_symbol"]
)
def test_find_definition_returns_definitions(query_type):
    index = _SymbolIndex([_Ref("as_dict", "src/agentfactory/brain.py", 102)])
    payload = _query(index, query_type)

    assert payload["status"] == "ok", payload
    assert payload["count"] == 1
    assert payload["definitions"][0]["file"] == "src/agentfactory/brain.py"
    assert payload["definitions"][0]["line"] == 102
    assert index.asked == ["as_dict"]


def test_find_definition_with_no_matches_is_not_an_error():
    payload = _query(_SymbolIndex([]), "find_definition", "missing_symbol")

    assert payload["status"] == "ok"
    assert payload["count"] == 0
    assert payload["definitions"] == []


def test_unknown_query_type_still_reports_available_types():
    payload = _query(_SymbolIndex([]), "no_such_query", "x")

    assert payload["status"] == "error"
    assert "find_definition" in payload["message"], "подсказка обязана перечислять новый тип"
