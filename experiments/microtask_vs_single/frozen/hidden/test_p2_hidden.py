from decimal import Decimal

from tinycalc.core import round_money
from tinycalc.formatting import format_total


def test_round_half_up():
    assert round_money("1.005") == Decimal("1.01")


def test_total_string_prices():
    assert format_total([("0.105", 2)]) == "$0.21"


def test_total_zero():
    assert format_total([("0.00", 5)]) == "$0.00"


def test_total_multiple_lines():
    assert format_total([("0.10", 3)]) == "$0.30"
