"""Independent recompute of E3/E4 from raw JSONL (does not read RESULTS.md)."""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

R = Path(__file__).resolve().parent / "results"


def load(name: str) -> list[dict]:
    return [json.loads(l) for l in (R / name).read_text(encoding="utf-8").splitlines() if l.strip()]


def cells(rows: list[dict]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        if r.get("ok") and r.get("digit") is not None:
            key = r["case"] if "variant" not in r else f"{r['case']}::{r['variant']}"
            out[key].append(r["digit"])
    return out


def m(xs: list[int]) -> float | None:
    return round(statistics.fmean(xs), 3) if xs else None


print("=== E3 (raw_e3.jsonl) ===")
rows = load("raw_e3.jsonl")
c = cells(rows)
for case in sorted(c):
    print(f"  {case:28s} mean={m(c[case])} vals={c[case]}")
for s in ["driver", "warehouse", "nurse", "engineer"]:
    nh, hm = m(c.get(f"{s}::no_harm", [])), m(c.get(f"{s}::harm", []))
    print(f"  leak {s}: {None if None in (nh, hm) else round(hm - nh, 3)}")
print(f"  pos_gap: {round(m(c['pos_control::severe']) - m(c['pos_control::mild']), 3)}")
print(f"  neg_delta: {round(m(c['neg_control::a']) - m(c['neg_control::b']), 3)}")

print("\n=== E4 run1 (raw_e4_run1.jsonl) ===")
c1 = cells(load("raw_e4_run1.jsonl"))
print({k: m(v) for k, v in sorted(c1.items())})
print("\n=== E4 run2 (raw_e4.jsonl) ===")
c2 = cells(load("raw_e4.jsonl"))
print({k: m(v) for k, v in sorted(c2.items())})
print("\n=== run1 vs run2 identical? ===")
print(c1 == c2)
