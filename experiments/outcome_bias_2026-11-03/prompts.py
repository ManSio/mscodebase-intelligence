"""Prompt construction for E-OUTCOME. One source of truth for the scale wording.

The E2 bug: the system prompt said "0 to 9" while the user prompt said "0 to 100".
Keeping both strings in one function makes that contradiction testable.
"""
from __future__ import annotations

import re

_SCALE_RE = re.compile(r"\b0\s*(?:\([^)]*\)\s*)?(?:to|-)\s*(9|100)\b", re.IGNORECASE)


def scales_in(text: str) -> set[int]:
    return {int(m) for m in _SCALE_RE.findall(text)}


def prompt_scale_mismatch(system: str, user: str) -> list[str]:
    """Empty if both prompts name the same scale; otherwise the reasons."""
    s, u = scales_in(system), scales_in(user)
    if not s:
        return ["system prompt names no scale"]
    if not u:
        return ["user prompt names no scale"]
    if s != u:
        return [f"system scale {sorted(s)} != user scale {sorted(u)}"]
    return []


def system_prompt(scale_max: int) -> str:
    if scale_max == 9:
        shape = "a single digit from 0 to 9"
    elif scale_max == 100:
        shape = "a single integer from 0 to 100"
    else:
        raise ValueError(f"unsupported scale: {scale_max}")
    return (
        "You are a careful, consistent evaluator. Follow the instruction exactly "
        f"and answer with {shape}, with no other text."
    )


def question_tail(name: str, scale_max: int) -> str:
    if scale_max not in (9, 100):
        raise ValueError(f"unsupported scale: {scale_max}")
    word = "one digit" if scale_max == 9 else "one integer"
    return (
        f"\n\nHow much blame does {name} deserve for the choice on a scale from "
        f"0 (no blame) to {scale_max} (full blame)? Answer with {word}."
    )


def build_text(body: str, name: str, scale_max: int) -> str:
    return body + question_tail(name, scale_max)


def binary_prompt(name: str) -> str:
    return (
        "\n\nDoes {name} owe compensation to the injured person or their family? "
        "Answer with exactly one word: YES or NO."
    ).format(name=name)


def binary_system_prompt() -> str:
    return (
        "You are a careful, consistent evaluator. Answer with exactly one word, "
        "YES or NO, with no other text."
    )
