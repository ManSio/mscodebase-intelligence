"""E73: refuse only when NO identifier occurs, not when the first one is absent.

The shipped rule read `per[first] == 0`, and on external commits the first token
is prose or a dotted annotation, so the answer was withheld while a later name
occurred hundreds of times (13 of 40 sqlalchemy commits, 8 of them hid the gold).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.core.di_container import ServiceCollection
from src.mcp.tools.investigate_tool import InvestigateTool, _abstains


def test_first_absent_but_another_present_does_not_abstain():
    assert _abstains({"_orm.registry": 0, "Declarative": 785}, False, False) is False


def test_nothing_occurs_still_abstains():
    assert _abstains({"zz_a81a24a0": 0}, False, False) is True


def test_a_known_symbol_never_withholds():
    assert _abstains({"Signer": 0}, True, False) is False


def test_include_neighbours_never_withholds():
    assert _abstains({"zz_a81a24a0": 0}, False, True) is False


def test_a_degraded_channel_never_withholds():
    # `per` exists only when the grep channel completed; empty means "unknown".
    assert _abstains({}, False, False) is False


def test_the_subject_occurring_is_an_answer():
    assert _abstains({"get_progress_file": 12, "progress": 40}, False, False) is False


def test_all_zero_with_extra_tokens_still_abstains():
    assert _abstains({"zz_a": 0, "zz_b": 0, "previously": 0}, False, False) is True


def test_an_unknown_counter_never_becomes_a_refusal():
    # `None`/negative is "the channel could not count", not "nothing occurs" -
    # the same fail-open rule as a degraded grep channel (E73 review, nit 4-5).
    assert _abstains({"a": None}, False, False) is False
    assert _abstains({"a": 0, "b": None}, False, False) is False
    assert _abstains({"a": -1}, False, False) is False


def _fake_tool(tmp_path: Path) -> InvestigateTool:
    """The stub used by tests/test_investigate.py: one search row, no symbols."""
    tool = InvestigateTool(ServiceCollection())

    async def _noop(*args, **kwargs):
        return None

    class _Searcher:
        async def hybrid_search_async(self, query, limit=5, rerank=None):
            return [{"file_path": "a.py", "line": 3, "text": "hit", "score": 1.0}]

    class _Symbols:
        def search_symbols(self, query, top_k=3):
            return []

        def has_symbol(self, name):
            return False

    class _Indexer:
        project_path = tmp_path

    tool.require_ready_project = _noop  # type: ignore[assignment]
    tool.resolve_searcher = lambda **kw: _Searcher()  # type: ignore[assignment]
    tool.resolve_symbol_index = lambda **kw: _Symbols()  # type: ignore[assignment]
    tool.resolve_indexer = lambda **kw: _Indexer()  # type: ignore[assignment]
    return tool


def test_all_zero_identifiers_refuse_and_hand_back_the_next_call(tmp_path):
    """The policy, end to end: nothing occurs -> no rows, and a machine-readable
    `next:` call instead of a sentence the caller has to parse (E69, option C)."""
    (tmp_path / "a.py").write_text("hit = 1\n", encoding="utf-8")
    tool = _fake_tool(tmp_path)

    out = asyncio.run(tool.execute(
        query="where is zz_ghost_one and zz_ghost_two defined",
        project_root=str(tmp_path),
    ))

    assert "results: 0" in out, out
    assert "verdict: abstain" in out, out
    assert "next: investigate(" in out, out
