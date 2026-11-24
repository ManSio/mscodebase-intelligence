"""Score frozen arms.json against frozen/HYPOTHESES.md. No re-runs, no edits.

Verdicts are DERIVED from data with the confirm/falsify thresholds written in
HYPOTHESES.md before the run; the dead zone between them yields INCONCLUSIVE.
(audit 2026-11-15: H4 used to be a hardcoded string)
"""
from __future__ import annotations

import gzip
import json
import re
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rows = json.loads((ROOT / "results" / "arms.json").read_text(encoding="utf-8"))


def pct(values, p):
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def stats(arm):
    t = [r[arm]["tokens"] for r in rows]
    ms = [r[arm]["ms"] for r in rows if r[arm]["ms"] is not None]
    hits = sum(r[arm]["hit"] for r in rows)
    return {
        "hits": hits,
        "hit_rate": round(hits / len(rows), 3),
        "tokens": {"min": min(t), "median": st.median(t), "p90": round(pct(t, 90)),
                   "max": max(t), "sum": sum(t)},
        "ms": ({"median": st.median(ms), "p90": round(pct(ms, 90))} if ms
               else {"measured": False,
                     "why": "same three calls as arm A inside one program: wall clock "
                            "is identical by construction, not a second measurement"}),
    }


def verdict(confirm: bool, falsify: bool) -> str:
    if confirm:
        return "CONFIRMED"
    if falsify:
        return "REFUTED"
    return "INCONCLUSIVE"


a_hit = [r for r in rows if r["A"]["hit"]]
b_lost = [r["id"] for r in a_hit if not r["B"]["hit"]]
c_lost = [r["id"] for r in a_hit if not r["C"]["hit"]]
ratios = [r["C"]["tokens"] / r["A"]["tokens"] for r in rows]
c_over_800 = [r["id"] for r in rows if r["C"]["tokens"] > 800]
c_over_1000 = [r["id"] for r in rows if r["C"]["tokens"] > 1000]
n_a = max(len(a_hit), 1)

# B's non-delivery has two mechanisms, and they need different protocol advice:
# a refusal (abstain/ask_rewrite) is a "ask again with another tool", while an
# extraction miss is "the fusion answer was wrong". Counting them as one number
# was audit blocker 1 (2026-11-15).
REFUSAL_RE = re.compile(r'"(ask_rewrite|abstain|insufficient_evidence|clarify)"')
b_refusals, b_misses = [], []
try:
    _raw = json.load(gzip.open(ROOT / "results" / "raw_texts" / "arm_texts.json.gz",
                               "rt", encoding="utf-8"))
except OSError:
    _raw = {}
for qid in b_lost:
    text = _raw.get(qid, {}).get("B", "")
    (b_refusals if REFUSAL_RE.search(text) else b_misses).append(qid)

verdicts = {
    "H1 (C keeps every gold A had: confirm <=5% lost, falsify >=3 cases)": {
        "lost_cases": len(c_lost),
        "of": len(a_hit),
        "verdict": verdict(len(c_lost) / n_a <= 0.05, len(c_lost) >= 3),
        "note": "near-tautological by construction: C projects A's own text; "
                "it measures what the filter drops, not what the projection adds",
    },
    "H2 (median tokens C/A: confirm <=0.20, falsify >0.30)": {
        "value": round(st.median(ratios), 3),
        "verdict": verdict(st.median(ratios) <= 0.20, st.median(ratios) > 0.30),
    },
    "H3 (investigate does not deliver gold: confirm >=20%, falsify <5%)": {
        "lost_cases": len(b_lost),
        "of": len(a_hit),
        "rate": round(len(b_lost) / n_a, 3),
        "refusals": b_refusals,
        "extraction_misses": b_misses,
        "extraction_rate": round(len(b_misses) / n_a, 3),
        "verdict": verdict(len(b_lost) / n_a >= 0.20, len(b_lost) / n_a < 0.05),
        "note": "frozen text said 'loses the exact path'; the split shows two mechanisms "
                "(refusal vs extraction), so the protocol advice differs per bucket",
    },
    "H4 (tokens_C <= 800 every case: falsify if >=5 cases >1000)": {
        "over_800": len(c_over_800),
        "over_1000": len(c_over_1000),
        "verdict": verdict(len(c_over_800) == 0, len(c_over_1000) >= 5),
        "max": max(r["C"]["tokens"] for r in rows),
    },
}

unreachable = [r["id"] for r in rows if not r["A"]["hit"]]
out = {
    "population": len(rows),
    "per_arm": {arm: stats(arm) for arm in "ACB"},
    "paired_on_A_hits": {
        "n": len(a_hit),
        "median_tokens": {arm: st.median([r[arm]["tokens"] for r in a_hit]) for arm in "ACB"},
        "median_ms": {
            arm: (st.median(vals) if (vals := [r[arm]["ms"] for r in a_hit
                                              if r[arm]["ms"] is not None]) else None)
            for arm in "ACB"
        },
    },
    "unreachable_by_arm_A": unreachable,
    "verdicts": verdicts,
}
(ROOT / "results" / "VERDICTS.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
