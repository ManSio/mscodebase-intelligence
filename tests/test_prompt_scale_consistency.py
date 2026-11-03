"""The prompt builder must never contradict itself about the scale.

This is the guard for the E2 bug: system said 0-9, user asked 0-100.
Run: python -m pytest tests/test_prompt_scale_consistency.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "outcome_bias_2026-11-03"))

import prompts  # noqa: E402


@pytest.mark.parametrize("scale", [9, 100])
def test_builder_is_consistent(scale):
    system = prompts.system_prompt(scale)
    user = prompts.question_tail("Dana", scale)
    assert prompts.prompt_scale_mismatch(system, user) == []
    assert str(scale) in system and str(scale) in user


def test_mismatch_is_detected_can_fail():
    # deliberately reproduce the E2 defect; the guard must catch it
    system = "Answer with a single digit from 0 to 9."
    user = "Blame on a scale from 0 (no blame) to 100 (full blame)? One integer."
    reasons = prompts.prompt_scale_mismatch(system, user)
    assert reasons, "guard must fail on the known E2 mismatch"
    assert "system scale" in reasons[0]


def test_missing_scale_is_an_error():
    assert prompts.prompt_scale_mismatch("answer briefly", "how much blame?") != []
    assert prompts.prompt_scale_mismatch("0 to 9", "how much blame?") != []


def test_unsupported_scale_is_rejected():
    with pytest.raises(ValueError):
        prompts.system_prompt(10)
    with pytest.raises(ValueError):
        prompts.question_tail("Dana", 7)
