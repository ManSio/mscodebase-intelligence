"""A4/A5 independent recomputation of the F5 judged + relang rates from judged_raw.json.

Reads ONLY the raw records (verdict strings), never judged_aggregate.json /
aggregate.json — those are claims under audit. Compares the recomputed totals
against the published numbers.
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "experiments" / "4A_unit_of_return" / "results"


def counts(raw_path: pathlib.Path) -> dict:
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    tab: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for rec in data["records"]:
        pop = rec["population"]
        for arm, blob in rec["arms"].items():
            for v in blob["verdicts"]:
                tab[(pop, arm)][1] += 1
                tab[(pop, arm)][0] += int(v == "correct")
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (pop, arm), (c, n) in tab.items():
        totals[arm][0] += c
        totals[arm][1] += n
    return {"per_pop": dict(tab), "per_arm": dict(totals)}


def report(tag: str, raw: pathlib.Path) -> None:
    print(f"\n=== {tag}  source={raw.relative_to(ROOT).as_posix()}")
    res = counts(raw)
    for (pop, arm), (c, n) in sorted(res["per_pop"].items()):
        print(f"  {pop:6} {arm}: {c}/{n} = {100 * c / n:.1f}%")
    for arm, (c, n) in sorted(res["per_arm"].items()):
        print(f"  ALL    {arm}: {c}/{n} = {100 * c / n:.1f}%")


def main() -> int:
    report("A4 F5 judged (trials=10, arms A-D, code+prose)", BASE / "f5judged" / "judged_raw.json")
    report("A5 F5 relang EN", BASE / "f5relang" / "en" / "judged_raw.json")
    report("A5 F5 relang RU", BASE / "f5relang" / "ru" / "judged_raw.json")

    en = counts(BASE / "f5relang" / "en" / "judged_raw.json")["per_arm"]["B"]
    ru = counts(BASE / "f5relang" / "ru" / "judged_raw.json")["per_arm"]["B"]
    print(f"\n[A5] EN {en[0]}/{en[1]} vs RU {ru[0]}/{ru[1]}"
          f"  delta={100 * (en[0] / en[1] - ru[0] / ru[1]):+.1f} pp")
    print("[A5] published: EN 30/80=37.5% vs RU 26/80=32.5%, CI overlap -> not significant")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
