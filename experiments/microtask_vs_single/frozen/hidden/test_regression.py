from tinycalc.core import mean
from tinycalc.formatting import format_total


def test_mean_single_value_regression():
    assert mean([5]) == 5


def test_total_plain_regression():
    assert format_total([("0.10", 1)]) == "$0.10"
