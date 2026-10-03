"""One implementation of the judge's verdict contract.

Why this file exists. Two scripts parsed the same judge's answer independently:

  - `scripts/f5_judged_run.py` took the LAST verdict word (fixed 2026-09-27);
  - `scripts/reconstruct_judge_cot.py` took the FIRST, and its fallback tested
    substrings with "incorrect" before "correct". So a self-correcting judge
    ("looks incorrect ... actually correct, final answer: correct") was recorded
    INVERTED, silently: every counter stayed green and `uncertain` was
    unreachable whenever any verdict word appeared.

The contract (measured on judged_cot_backfill.json, 1014 judge sessions):
the FINAL decision is the LAST one stated. Last JSON "verdict" match wins;
otherwise the last verdict-word mention wins. last==final 842/1014 vs
first-match 820/1014; on the 61 flip sessions last==final 53/61 (87%) vs
first==final 34/61 (56%). No explicit "final verdict:" marker exists in the
wild (0/61), so last-match IS the contract.

Imported by both consumers so that a third copy cannot appear.
"""
from __future__ import annotations

import re

VERDICT_WORDS = ("correct", "incorrect", "uncertain")
VERDICT_ALT = "|".join(VERDICT_WORDS)

# \b boundaries matter: "incorrect" contains "correct", and "correctly" is not a
# verdict. The old substring fallback could not tell them apart.
VERDICT_RE = re.compile(rf"\b({VERDICT_ALT})\b", re.I)
JSON_VERDICT_RE = re.compile(rf'"verdict"\s*:\s*"?({VERDICT_ALT})"?', re.I)


def parse_verdict(text: str) -> str:
    """Return 'correct' | 'incorrect' | 'uncertain' from a judge answer."""
    matches = JSON_VERDICT_RE.findall(text or "")
    if matches:
        return matches[-1].lower()
    hits = VERDICT_RE.findall(text or "")
    if hits:
        return hits[-1].lower()
    return "uncertain"