"""Tests for the lab fixture. test_rpn_order_bug currently FAILS (planted bug)."""
import pytest

from src.calc import Calculator, Operation
from src.rpn import evaluate


def test_add_ok() -> None:
    assert Calculator().add(1, 2) == 3


def test_div_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        Calculator().div(1, 0)


def test_apply_uses_operation() -> None:
    assert Calculator().apply(Operation("mul", (3, 4))) == 12


def test_rpn_order_bug() -> None:
    # 5 2 -  == 3 in RPN; planted bug: args are popped in reverse order -> -3
    result = evaluate("5 2 -")
    assert result == 3, f"expected 3, got {result}"


def test_rpn_compound() -> None:
    assert evaluate("2 3 * 4 +") == 10