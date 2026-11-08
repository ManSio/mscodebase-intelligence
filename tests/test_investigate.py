"""investigate: identifier extraction, merge/dedup, honest empty answer.

The tool is the "one query in" entry: it runs search + symbols + grep in
parallel and merges them by (file, line), keeping every channel that found the
item. A channel that fails only degrades the answer.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.core.di_container import ServiceCollection
from src.mcp.tools.investigate_tool import InvestigateTool, _identifiers, _merge


def test_identifiers_prefer_code_shapes():
    ids = _identifiers("how does IndexStatusReporter compute total_chunks in the indexer")
    assert ids[0] == "IndexStatusReporter"
    assert "total_chunks" in ids
    assert "the" not in ids


def test_merge_dedups_and_keeps_channels():
    merged = _merge(
        [
            {"file": "a.py", "line": 10, "text": "from search", "score": 0.4, "channels": {"search"}},
            {"file": "a.py", "line": 10, "text": "", "score": 1.0, "channels": {"symbol"}},
            {"file": "b.py", "line": 5, "text": "grep only", "score": 0.5, "channels": {"grep"}},
        ],
        limit=10,
    )
    assert len(merged) == 2
    first = merged[0]
    assert first["file"] == "a.py" and first["line"] == 10
    assert first["channels"] == {"search", "symbol"}
    assert first["score"] == 1.0


def test_empty_result_is_not_invented():
    tool = InvestigateTool(ServiceCollection())
    text = tool._format("nothing here", [], [], [], [])
    assert "Ничего не найдено" in text


def test_memory_hits_match_title_or_body():
    from src.mcp.tools.investigate_tool import _memory_hits

    nodes = [
        {"data": {"title": "ADR-0003 verify-on-read", "description": "lazy validation"}},
        {"data": {"title": "Something else", "description": "unrelated"}},
    ]
    hits = _memory_hits(nodes, "how does verify-on-read work")
    assert hits == ["ADR-0003 verify-on-read"]


def test_memory_hits_ignore_short_tokens():
    from src.mcp.tools.investigate_tool import _memory_hits

    assert _memory_hits([{"title": "x"}], "how do we do it") == []


def _fake_tool(tmp_path: Path) -> InvestigateTool:
    tool = InvestigateTool(ServiceCollection())

    async def _noop(*args, **kwargs):
        return None

    class _Searcher:
        async def hybrid_search_async(self, query, limit=5):
            return [{"file_path": "a.py", "line": 3, "text": "hit", "score": 1.0}]

    class _Symbols:
        def search_symbols(self, query, top_k=3):
            return []

    class _Indexer:
        project_path = tmp_path

    tool.require_ready_project = _noop  # type: ignore[assignment]
    tool.resolve_searcher = lambda **kw: _Searcher()  # type: ignore[assignment]
    tool.resolve_symbol_index = lambda **kw: _Symbols()  # type: ignore[assignment]
    tool.resolve_indexer = lambda **kw: _Indexer()  # type: ignore[assignment]
    return tool


def test_execute_returns_merged_answer(tmp_path):
    (tmp_path / "a.py").write_text("hit = 1\n", encoding="utf-8")
    tool = _fake_tool(tmp_path)

    out = asyncio.run(tool.execute("where is hit", project_root=str(tmp_path)))

    assert "investigate" in out
    assert "a.py:3" in out
    assert "[search" in out
