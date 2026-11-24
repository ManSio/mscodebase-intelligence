"""Issue #150, дефект 1: «not found» в окне после появления файла.

Репро на реальном проекте: индекс собран → новый файл → get_symbol_info
отвечает not found, а grep находит. Здесь та же логика на фейковом индексере:
настоящий путь (сверка свежести → повторный запрос) без MCP-сервера.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from src.core.di_container import ServiceCollection
from src.mcp.tools.search_tools import GetSymbolInfoTool


class _Symbols:
    """Индекс, который «прозревает» только после сверки свежести."""

    def __init__(self, project: Path) -> None:
        self.project = project
        self.fresh = False

    def build_call_graph(self, query, depth=2):
        if not self.fresh:
            return {"definition": [], "callers": [], "callees": []}
        return {
            "definition": [{"file": str(self.project / "new_mod.py"), "line": 1, "kind": "function"}],
            "callers": [],
            "callees": [],
        }

    def search_symbols(self, query, top_k=3):
        return []


class _Indexer:
    def __init__(self, symbols: _Symbols, changed: int = 1, error: Exception | None = None):
        self.project_path = symbols.project
        self._symbols = symbols
        self._changed = changed
        self._error = error
        self.calls = 0

    def verify_index_freshness(self, project_path):
        self.calls += 1
        if self._error is not None:
            raise self._error
        if self._changed:
            self._symbols.fresh = True
        return self._changed


def _tool(tmp_path: Path, **kwargs) -> tuple[GetSymbolInfoTool, _Symbols, _Indexer]:
    symbols = _Symbols(tmp_path)
    indexer = _Indexer(symbols, **kwargs)
    tool = GetSymbolInfoTool(ServiceCollection())

    async def _noop(*_args, **_kwargs):
        return None

    tool.require_ready_project = _noop  # type: ignore[assignment]
    tool.resolve_symbol_index = lambda **_kw: symbols  # type: ignore[assignment]
    tool.resolve_indexer = lambda **_kw: indexer  # type: ignore[assignment]
    return tool, symbols, indexer


def _run(tool: GetSymbolInfoTool, project: Path) -> str:
    return asyncio.run(tool.execute("beta_symbol", project_root=str(project)))


def test_symbol_found_after_refresh(tmp_path: Path):
    tool, _, indexer = _tool(tmp_path)

    out = _run(tool, tmp_path)

    assert "1 defs" in out, out
    assert "Index refreshed" in out, out
    assert indexer.calls == 1, "сверка свежести должна быть ровно одна"


def test_refresh_not_called_when_symbol_is_found(tmp_path: Path):
    tool, symbols, indexer = _tool(tmp_path)
    symbols.fresh = True

    out = _run(tool, tmp_path)

    assert "1 defs" in out, out
    assert indexer.calls == 0, "при найденном символе сверка не нужна"


def test_stale_answer_when_refresh_fails(tmp_path: Path):
    tool, _, _ = _tool(tmp_path, error=RuntimeError("db is locked"))

    out = _run(tool, tmp_path)

    assert "may be stale" in out, out
    assert "db is locked" in out, out
    assert "not declared in the project" not in out


def test_honest_absence_after_refresh_without_changes(tmp_path: Path):
    tool, _, indexer = _tool(tmp_path, changed=0)

    out = _run(tool, tmp_path)

    assert "not found" in out, out
    assert "may be stale" not in out
    assert indexer.calls == 1
