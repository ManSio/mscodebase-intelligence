"""E73: refuse only when NO identifier occurs, not when the first one is absent.

The shipped rule read `per[first] == 0`, and on external commits the first token
is prose or a dotted annotation, so the answer was withheld while a later name
occurred hundreds of times (13 of 40 sqlalchemy commits, 8 of them hid the gold).
"""

from __future__ import annotations

from src.mcp.tools.investigate_tool import _abstains


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
