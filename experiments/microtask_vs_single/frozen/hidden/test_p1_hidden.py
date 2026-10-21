import pytest

from tinycalc.core import mean


def test_mean_float():
    assert mean([1, 2]) == 1.5


def test_mean_empty():
    with pytest.raises(ValueError):
        mean([])


def test_mean_single():
    assert mean([0]) == 0
