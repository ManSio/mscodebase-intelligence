"""Combine the three arms into the table the report quotes.

Fails (exit 2) if any arm is missing: a partial table would read as "the other
arm found nothing", which is the silent-zero class.

Run: python experiments/xerj_2026_11/ru_vs_dense/summarize.py
"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def load(arm: str) -> dict:
    path = RESULTS / f"{arm}.json"
    if not path.exists():
        print(f"MISSING ARM {arm}: {path} (not measured, not zero)")
        raise SystemExit(2)
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    arms = {arm: load(arm) for arm in ("A", "B", "C")}
    overlap = json.loads((HERE / "frozen" / "overlap.json").read_text(encoding="utf-8"))
    hard = {cid for cid, row in overlap["cases"].items() if row["hard_turn1"]}

    print("| arm | mode | hit@turn1 | hit@turn3 | turns total |")
    print("|---|---|---:|---:|---:|")
    for name, data in arms.items():
        total = data["summary"]["cases"]
        turns = sum(
            c["turns_to_success"] for c in data["cases"].values()
            if c["turns_to_success"]
        )
        print(
            f"| {name} | {data['mode']}/{data['lang']} | "
            f"{data['summary']['hit@turn1']}/{total} | "
            f"{data['summary']['hit@turn3']}/{total} | {turns} |"
        )

    print("\n| case | gold | A ranks | B ranks | C ranks |")
    print("|---|---|---|---|---|")
    for cid in arms["A"]["cases"]:
        print(
            f"| {cid} | {arms['A']['cases'][cid]['gold']} | "
            f"{arms['A']['cases'][cid]['ranks']} | "
            f"{arms['B']['cases'][cid]['ranks']} | "
            f"{arms['C']['cases'][cid]['ranks']} |"
        )

    print(f"\nhard subset (no EN token overlap at turn 1): {sorted(hard) or 'EMPTY'}")
    for name, data in arms.items():
        hits = sum(1 for cid in hard if data["cases"][cid]["hit@turn1"])
        print(f"  {name}: {hits}/{len(hard) if hard else 0}")

    print("\ndense_score rows per arm (0 everywhere means the dense path did not run):")
    for name, data in arms.items():
        values = [sum(c["dense_rows"]) for c in data["cases"].values()]
        print(f"  {name}: {sum(values)} rows across {len(values)} cases")

    print("\ncontrols:")
    for name, data in arms.items():
        print(f"  {name}: {data['controls']}")

    b_only = sorted(
        cid for cid in arms["B"]["cases"]
        if arms["B"]["cases"][cid]["hit@turn3"] and not arms["A"]["cases"][cid]["hit@turn3"]
    )
    c_only = sorted(
        cid for cid in arms["C"]["cases"]
        if arms["C"]["cases"][cid]["hit@turn3"] and not arms["B"]["cases"][cid]["hit@turn3"]
    )
    print(f"\nB succeeds where A fails (3 turns): {b_only or 'none'}")
    print(f"C succeeds where B fails (3 turns): {c_only or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
