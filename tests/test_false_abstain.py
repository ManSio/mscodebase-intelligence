"""E73: refuse only when NO identifier occurs, not when the first one is absent.

The shipped rule read `per[first] == 0`, and on external commits the first token
is prose or a dotted annotation, so the answer was withheld while a later name
occurred hundreds of times (13 of 40 sqlalchemy commits, 8 of them hid the gold).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

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


def _g2_tokens(present_slot: int) -> list[str]:
    """Four identifiers whose extraction order is fixed by length.

    `_identifiers` sorts by (code_shape, length), so a longer name is always
    ranked first. Padding the slots to 60/45/30/15 characters pins the position
    of the one name that occurs, without touching the ranking code.
    """
    lengths = [60, 45, 30, 15]
    tokens = []
    for index, size in enumerate(lengths):
        base = f"zz_{chr(ord('a') + index)}_"
        suffix = "_present" if index + 1 == present_slot else ""
        tokens.append(base + "q" * (size - len(base) - len(suffix)) + suffix)
    return tokens


@pytest.mark.parametrize("slot", [1, 2, 3, 4])
def test_every_extracted_identifier_is_counted(tmp_path, slot):
    """G2: `per` must cover every identifier `_identifiers` returns (up to 4).

    Before this fix only the first two were counted, so a name at slot 3 or 4
    that does occur could not stop the refusal: the answer was emptied while the
    file that answers it was in the index. Slots 1-2 are the controls (they were
    counted before and after).
    """
    names = _g2_tokens(slot)
    present = names[slot - 1]
    (tmp_path / "a.py").write_text(f"{present} = 1\n", encoding="utf-8")
    tool = _fake_tool(tmp_path)

    out = asyncio.run(tool.execute(
        query="where is " + " ".join(names) + " defined",
        project_root=str(tmp_path),
    ))

    identifiers_line = next(
        (line for line in out.splitlines() if "identifiers:" in line), "")
    listed = [n.strip() for n in identifiers_line.split("identifiers:")[1].split(",")]
    assert listed[slot - 1] == present, identifiers_line
    assert "results: 0" not in out, out
    # The exact line names the FIRST counted identifier, which may be an absent
    # one; G1's "the subject does not occur" is then a correct statement about
    # that name. What must never appear is a claim that the one name that DOES
    # occur is absent.
    assert f"{present}=0" not in out, out


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
