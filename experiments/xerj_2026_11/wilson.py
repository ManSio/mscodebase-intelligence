"""Wilson 95% intervals for the panel numbers in this series.

Usage:
    python experiments/xerj_2026_11/wilson.py

Kept as a script, not a library: every report quotes it as the command that
reproduces the interval next to the rate.
"""

from __future__ import annotations

import math

Z = 1.96


def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    """95% Wilson score interval for k successes out of n."""
    if n <= 0:
        raise SystemExit("empty population: no interval, no rate")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


CELLS = (
    ("XERJ positive top1, control (E62)", 5, 16),
    ("XERJ positive top1, treatment (E62)", 6, 16),
    ("XERJ positive any@8 (E62)", 10, 16),
    ("mcp_audit positive top1 (E62)", 9, 17),
    ("mcp_audit positive any@8 (E62)", 14, 17),
    ("XERJ negative, no rows (E62)", 4, 4),
    ("held-out top1 (external, 12)", 11, 12),
    ("rewrite ON top1 (23 asks)", 4, 23),
    ("rewrite OFF/smart top1 (23 asks)", 5, 23),
)


def main() -> int:
    for label, k, n in CELLS:
        lo, hi = wilson(k, n)
        print(f"{label:<40} {k}/{n} = {k/n:.3f}  95% CI [{lo:.2f}, {hi:.2f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
