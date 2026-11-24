"""Paired comparison of two arms on the same 48 frozen cases (exact McNemar)."""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rows = json.loads((ROOT / "results" / "arms.json").read_text(encoding="utf-8"))


def exact_binom_two_sided(k: int, n: int) -> float:
    """Two-sided exact binomial p for k successes out of n at p=0.5."""
    if n == 0:
        return 1.0
    probs = [math.comb(n, i) / 2 ** n for i in range(n + 1)]
    observed = probs[k]
    return min(1.0, sum(p for p in probs if p <= observed + 1e-12))


def mcnemar(a: str, b: str) -> dict:
    a_only = [r["id"] for r in rows if r[a]["hit"] and not r[b]["hit"]]
    b_only = [r["id"] for r in rows if r[b]["hit"] and not r[a]["hit"]]
    n = len(a_only) + len(b_only)
    k = min(len(a_only), len(b_only))
    return {
        "pair": f"{a} vs {b}",
        f"{a}_only": len(a_only),
        f"{b}_only": len(b_only),
        "discordant": n,
        "exact_p": round(exact_binom_two_sided(k, n), 3),
        "significant_at_0.05": exact_binom_two_sided(k, n) < 0.05,
    }


for pair in (("A", "B"), ("A", "C"), ("C", "B")):
    print(json.dumps(mcnemar(*pair), ensure_ascii=False))
