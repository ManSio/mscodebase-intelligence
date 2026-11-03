"""Canned tests for the exact readout. Hand-made numbers, no model.

Run: python -m pytest tests/test_readout.py -q
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "outcome_bias_2026-11-03"))

import readout  # noqa: E402


def one_hot(d, p=1.0):
    probs = [0.0] * 10
    probs[d] = p
    return probs


def test_expected_blame_basic():
    assert readout.expected_blame(one_hot(7)) == (7.0, 1.0)
    assert readout.expected_blame(one_hot(0)) == (0.0, 1.0)
    assert readout.expected_blame(one_hot(9)) == (9.0, 1.0)


def test_expected_blame_renormalises_over_digits():
    probs = [0.0] * 10
    probs[2], probs[4] = 0.25, 0.25
    assert readout.expected_blame(probs) == (3.0, 0.5)


def test_expected_blame_uniform_is_middle():
    blame, mass = readout.expected_blame([0.1] * 10)
    assert math.isclose(blame, 4.5)
    assert math.isclose(mass, 1.0)


def test_zero_mass_is_nan_not_fake_zero():
    blame, mass = readout.expected_blame([0.0] * 10)
    assert math.isnan(blame) and mass == 0.0


def test_wrong_length_and_negative_are_errors():
    with pytest.raises(ValueError):
        readout.expected_blame([0.5, 0.5])
    with pytest.raises(ValueError):
        readout.expected_blame([-0.1] + [0.1] * 9)


def test_mass_gate_passes_and_fails():
    assert readout.mass_gate(one_hot(4)) == []
    assert readout.mass_gate([0.05] * 10) != []  # mass 0.5


def test_fraction_restored_and_removed():
    assert math.isclose(readout.fraction_restored(4.5, 3.0, 5.0), 0.75)
    assert math.isclose(readout.fraction_restored(3.0, 3.0, 5.0), 0.0)
    assert math.isclose(readout.fraction_restored(5.0, 3.0, 5.0), 1.0)
    assert math.isclose(readout.fraction_removed(4.0, 3.56, 6.28), 2.28 / 2.72)
    with pytest.raises(ValueError):
        readout.fraction_restored(4.0, 3.0, 3.0)


def test_parse_int_respects_scale():
    assert readout.parse_int("7", 9) == 7
    assert readout.parse_int("100", 100) == 100
    assert readout.parse_int("100", 9) is None
    assert readout.parse_int("no number", 9) is None


def test_scale_following_detector_can_fail():
    # the concrete E2 failure: a 0-100 prompt answered 0..9 everywhere
    flags = readout.detect_scale_following([2, 8, 0, 9], 100)
    assert flags, "detector must flag all-values<=9 on a 0-100 scale"
    # one wider answer proves the model can use the scale -> not a failure
    assert readout.detect_scale_following([2, 8, 42], 100) == []
    # the narrow scale itself is never a failure
    assert readout.detect_scale_following([2, 8], 9) == []
    # empty input is a stop, not a pass
    assert readout.detect_scale_following([], 100) != []


def test_parse_yes_no():
    assert readout.parse_yes_no("YES") is True
    assert readout.parse_yes_no("no.") is False
    assert readout.parse_yes_no("maybe") is None
    assert readout.parse_yes_no("YESTERDAY") is None


def test_digit_probs_from_logprobs():
    top = [
        {"token": "3", "logprob": math.log(0.6)},
        {"token": "4", "logprob": math.log(0.4)},
        {"token": " ", "logprob": math.log(0.9)},
    ]
    probs = readout.digit_probs_from_logprobs(top)
    assert math.isclose(probs[3], 0.6, rel_tol=1e-9)
    assert math.isclose(probs[4], 0.4, rel_tol=1e-9)
    blame, mass = readout.expected_blame(probs)
    assert math.isclose(blame, 3.4)
    assert math.isclose(mass, 1.0)
    assert readout.digit_probs_from_logprobs([{"token": "x", "logprob": 0.0}]) is None
