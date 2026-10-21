from decimal import Decimal

from tinycalc.core import mean, round_money
from tinycalc.formatting import format_total


def test_mean_basic():
    assert mean([2, 4, 6]) == 4


def test_round_money_basic():
    assert round_money("1.005") == Decimal("1.01")


def test_total_half_up():
    assert format_total([("1.005", 1)]) == "$1.01"
