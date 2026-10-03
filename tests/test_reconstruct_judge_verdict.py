"""Verdict parsing in scripts/reconstruct_judge_cot.py — previously untested.

KNOWN_ISSUES recorded this class as Fixed on 2026-09-27, but only for
scripts/f5_judged_run.py. reconstruct_judge_cot.py kept its own first-match
substring parser, so a self-correcting judge was recorded INVERTED and silently:
every counter stayed green. Two locations carried the logic; one was buggy.

The control at the bottom re-implements the old parser and asserts it disagrees —
so this file cannot pass while the old behaviour is still in place.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


recon = _load("reconstruct_judge_cot")
f5 = _load("f5_judged_run")

# The inversion case from KNOWN_ISSUES, verbatim in shape.
INVERSION = (
    "At first this looks incorrect, but checking the arithmetic again it is "
    "actually correct, final answer: correct"
)


def test_self_correction_is_not_inverted():
    assert recon._parse_verdict(INVERSION) == "correct"


def test_last_json_verdict_wins():
    text = '{"verdict": "incorrect"}\nOn reflection: {"verdict": "correct"}'
    assert recon._parse_verdict(text) == "correct"
    text_rev = '{"verdict": "correct"}\nOn reflection: {"verdict": "incorrect"}'
    assert recon._parse_verdict(text_rev) == "incorrect"


def test_no_verdict_word_is_uncertain():
    assert recon._parse_verdict("I don't know.") == "uncertain"


def test_empty_input_is_uncertain():
    assert recon._parse_verdict("") == "uncertain"
    assert recon._parse_verdict(None) == "uncertain"


def test_substring_is_not_a_verdict():
    """'incorrectly'/'correctly' are not verdicts; the old scan could not tell."""
    assert recon._parse_verdict("the answer was stated incorrectly") == "uncertain"
    assert recon._parse_verdict("he answered correctly") == "uncertain"


def test_plain_single_verdicts_unchanged():
    assert recon._parse_verdict("correct") == "correct"
    assert recon._parse_verdict("incorrect") == "incorrect"
    assert recon._parse_verdict("uncertain") == "uncertain"


def test_mentions_helper_still_exported():
    """reconstruct_judge_cot.py:133 uses VERDICT_RE to list the words mentioned."""
    text = "first incorrect, then correct"
    assert sorted({w.lower() for w in recon.VERDICT_RE.findall(text)}) == ["correct", "incorrect"]


def test_both_scripts_share_one_implementation():
    """N of M: 2 of 2 locations carried this logic, so they must be one object."""
    assert recon._parse_verdict is f5._parse_verdict


@pytest.mark.parametrize("text,expected", [
    (INVERSION, "correct"),
    ("looks correct at first ... should be uncertain", "uncertain"),
    ("he answered correctly", "uncertain"),
])
def test_old_first_match_parser_disagrees(text, expected):
    """NEGATIVE CONTROL: the pre-fix parser must fail these, not agree."""
    import re

    json_re = re.compile(r'"verdict"\s*:\s*"?(correct|incorrect|uncertain)"?', re.I)

    def old_parse(t: str) -> str:
        m = json_re.search(t or "")
        if m:
            return m.group(1).lower()
        low = (t or "").lower()
        for v in ("incorrect", "correct", "uncertain"):
            if v in low:
                return v
        return "uncertain"

    assert old_parse(text) != expected
    assert recon._parse_verdict(text) == expected
