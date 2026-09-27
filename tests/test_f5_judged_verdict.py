"""Guard for the explicit-final verdict contract (scripts/f5_judged_run.py).

Validated on experiments/4A_unit_of_return/results/f5judged/judged_cot_backfill.json
(1014 judge sessions, 2026-09-27): last-match == final 842/1014, flips 53/61.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "f5_judged_run", PROJECT_ROOT / "scripts" / "f5_judged_run.py"
)
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)
_parse_verdict = _mod._parse_verdict

BACKFILL = (
    PROJECT_ROOT
    / "experiments"
    / "4A_unit_of_return"
    / "results"
    / "f5judged"
    / "judged_cot_backfill.json"
)


def test_single_json_verdicts_unchanged():
    assert _parse_verdict('{"verdict": "correct"}') == "correct"
    assert _parse_verdict('```json\n{"verdict": "incorrect"}\n```') == "incorrect"
    assert _parse_verdict('{"verdict":"uncertain"}') == "uncertain"


def test_no_mention_defaults_uncertain():
    assert _parse_verdict("I don't know.") == "uncertain"
    assert _parse_verdict("") == "uncertain"


def test_self_correction_json_pos():
    # Old first-match parser returned "incorrect" here (quoted example first).
    text = ('The user wants JSON with "verdict": "incorrect" if wrong. '
            'Candidate states the fact. Final: {"verdict": "correct"}')
    assert _parse_verdict(text) == "correct"


def test_self_correction_json_neg():
    text = ('Example format {"verdict": "correct"}. The candidate says I don\'t know, '
            'states nothing. Final: {"verdict": "incorrect"}')
    assert _parse_verdict(text) == "incorrect"


def test_self_correction_words_only_pos():
    # Haiku-style: starts "looks incorrect", ends correct. No JSON at all.
    text = ("At first glance this looks incorrect, the wording differs. "
            "But it states the reference fact, so actually correct.")
    assert _parse_verdict(text) == "correct"


def test_self_correction_words_only_neg():
    text = ("Seems correct at first, but the incident numbers cannot be verified "
            "from the reference. This should be uncertain because I cannot tell.")
    assert _parse_verdict(text) == "uncertain"


def test_real_backfill_agreement():
    """Regression on real judge data: last-match must hold its measured rate."""
    if not BACKFILL.exists():
        import pytest

        pytest.skip("backfill artifact absent")
    d = json.loads(BACKFILL.read_text(encoding="utf-8"))
    total = agree = flips = flips_ok = 0
    for q in d["queries"]:
        for s in q["sessions"]:
            total += 1
            if _parse_verdict(s["cot_text"]) == s["verdict_final"]:
                agree += 1
            if s["has_flip"]:
                flips += 1
                if _parse_verdict(s["cot_text"]) == s["verdict_final"]:
                    flips_ok += 1
    assert total == 1014, total
    assert flips == 61, flips
    assert agree >= 840, agree  # measured 842
    assert flips_ok >= 50, flips_ok  # measured 53
