"""Judge-free readout primitives for E-OUTCOME.

All pure functions. The exact readout mirrors the idea (not the code) of the
external report we audited: expected blame over digit probabilities, renormalised
over digit mass, with a mass gate. Independent implementation, canned tests.
"""
from __future__ import annotations

import math
import re


def expected_blame(digit_probs: list[float]) -> tuple[float, float]:
    """Return (expected blame, digit mass).

    digit_probs[d] = probability of the digit d (0..9). Blame is renormalised over
    the digits, so probability on non-digit tokens neither pulls it up nor down;
    it shows up in the mass. Zero mass -> (nan, 0.0), never a fake 0.
    """
    if len(digit_probs) != 10:
        raise ValueError(f"need 10 digit probabilities, got {len(digit_probs)}")
    if any(p < 0 for p in digit_probs):
        raise ValueError("negative probability")
    mass = sum(digit_probs)
    if mass == 0:
        return math.nan, 0.0
    return sum(d * p for d, p in enumerate(digit_probs)) / mass, mass


def digit_mass(digit_probs: list[float]) -> float:
    return sum(digit_probs)


def mass_gate(digit_probs: list[float], min_mass: float = 0.9) -> list[str]:
    """Stop reasons; empty means the read is a number answer."""
    _, mass = expected_blame(digit_probs)
    return [] if mass >= min_mass else [f"digit mass {mass:.3f} < {min_mass}"]


def fraction_restored(patched: float, no_harm: float, harm: float) -> float:
    """Share of the leak one swap brought back: 0 = none, 1 = all."""
    if harm == no_harm:
        raise ValueError("harm and no_harm are equal; fraction is undefined")
    return (patched - no_harm) / (harm - no_harm)


def fraction_removed(patched: float, no_harm: float, harm: float) -> float:
    """Share of the leak removed; same formula with legs swapped."""
    return fraction_restored(patched, harm, no_harm)


def parse_int(content: str, scale_max: int) -> int | None:
    """First integer 0..scale_max, or None. Does not repair a misspelled scale."""
    if scale_max == 9:
        m = re.search(r"(?<!\d)([0-9])(?!\d)", content)
        return int(m.group(1)) if m else None
    m = re.search(r"(?<!\d)(\d{1,3})(?!\d)", content)
    if not m:
        return None
    value = int(m.group(1))
    return value if 0 <= value <= scale_max else None


def detect_scale_following(values: list[int], scale_max: int) -> list[str]:
    """Flags for 'the model did not answer on this scale'.

    The concrete failure we hit: a 0-100 prompt answered with 0..9 everywhere.
    A single >9 answer is enough to prove the model *can* use the wider scale, so
    the flag only fires when every parsed value is <= 9.
    """
    if not values:
        return ["no values"]
    if scale_max <= 9:
        return []
    if all(0 <= v <= 9 for v in values):
        return [f"all {len(values)} values <= 9 on a 0-{scale_max} scale"]
    return []


def parse_yes_no(content: str) -> bool | None:
    """First standalone YES/NO word (case-insensitive), else None."""
    m = re.search(r"\b(YES|NO)\b", content.upper())
    if not m:
        return None
    return m.group(1) == "YES"


def digit_probs_from_logprobs(first_token_top: list[dict]) -> list[float] | None:
    """Build 10 digit probabilities from an OpenAI-style top_logprobs list.

    Each entry: {"token": str, "logprob": float}. Tokens that are not a single
    digit 0-9 are ignored. Returns None if no digit token is present.
    """
    probs = [0.0] * 10
    seen = False
    for entry in first_token_top:
        tok = str(entry.get("token", "")).strip()
        if len(tok) != 1 or tok not in "0123456789":
            continue
        lp = entry.get("logprob")
        if lp is None:
            continue
        probs[int(tok)] += math.exp(float(lp))
        seen = True
    total = sum(probs)
    if not seen or total <= 0:
        return None
    # top_logprobs is truncated; renormalising over the returned digits is the
    # same convention the mass gate checks. Mass < 1 is reported, not hidden.
    return probs
