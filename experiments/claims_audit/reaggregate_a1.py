"""A1/A6 re-aggregation: independently re-derive the E7/F4 pinned-variant verdicts
from stored run_*.txt, then compare against the recorded manifest.

The recorded manifest is the CLAIM UNDER AUDIT, so validity is re-derived here
from raw text only. Gold mapping for must-hit items is derived from the frozen
handout's own index (symptom description -> entry slug), not from RESULTS.md.

Read-only. No network, no LLM.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNS = ROOT / "experiments" / "4A_unit_of_return" / "results" / "pinned_variant"

ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*$", re.MULTILINE)

# Gold derived from frozen/e7_HANDOUT_EN.recovered.md: item text -> index entry slug.
GOLD_MUST_HIT = {
    1: "a-component-that-needs-starting-passes-every-behaviour-test",
    4: "a-surviving-mutant-can-mean-the-code-is-dead",
    9: "a-control-built-from-the-treated-arm-is-not-a-control",
}
MUST_NONE = (3, 6, 11)
ITEM16 = 16


def parse(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    answers = {int(n): v.strip() for n, v in ROW.findall(text)}
    return {
        "run": path.name,
        "answers": answers,
        "n_items": len(answers),
        "none": sorted(i for i, v in answers.items() if v.upper() == "NONE"),
    }


def judge(r: dict) -> dict:
    """Valid == 16 items answered AND must-hit correct AND must-NONE silent."""
    fails: list[str] = []
    if r["n_items"] != 16:
        fails.append(f"items={r['n_items']} (expected 16)")
    for item, gold in GOLD_MUST_HIT.items():
        got = r["answers"].get(item, "<missing>")
        if got != gold:
            fails.append(f"must-hit #{item}={got!r} != {gold!r}")
    for item in MUST_NONE:
        got = r["answers"].get(item, "<missing>")
        if got.upper() != "NONE":
            fails.append(f"must-NONE #{item}={got!r}")
    i16 = r["answers"].get(ITEM16, "<missing>")
    if i16.upper() != "NONE":
        fails.append(f"#16={i16!r} (expected NONE)")
    return {"run": r["run"], "valid": not fails, "fails": fails, "item16": i16}


def main() -> int:
    files = sorted(RUNS.glob("run_*.txt"))
    print(f"[A1] dir={RUNS.name}  run files={len(files)}")
    results = [parse(f) for f in files]
    for r in results:
        print(f"\n--- {r['run']}  items={r['n_items']}  NONE={r['none']}")

    verdicts = [judge(r) for r in results]
    valid = [v for v in verdicts if v["valid"]]
    print(f"\n[A1] RE-DERIVED valid: {len(valid)}/{len(verdicts)}")
    print(f"[A1] RE-DERIVED '#16 -> NONE' in all runs: "
          f"{sum(1 for v in verdicts if v['item16'].upper() == 'NONE')}/{len(verdicts)}")
    print(f"[A1] RE-DERIVED controls (must-hit 3/3 + must-NONE 3/3) in valid runs: "
          f"{sum(1 for v in valid if not v['fails'])}/{len(valid)}")
    bad = [v for v in verdicts if not v["valid"]]
    for v in bad:
        print(f"[A1] INVALID {v['run']}: {v['fails']}")
    n11 = [r["run"] for r in results if 11 not in r["none"]]
    print(f"[A1] runs with #11 NOT NONE: {n11}  (declared FP-rate 1/11)")

    recorded = json.loads((RUNS / "manifest.json").read_text(encoding="utf-8"))["results"]
    rec = {r["file"]: r for r in recorded}
    mismatch = [
        (v["run"], v["valid"], rec.get(v["run"], {}).get("valid"))
        for v in verdicts
        if rec.get(v["run"], {}).get("valid") != v["valid"]
    ]
    print(f"\n[A1] recorded-vs-rederived verdict mismatches: {len(mismatch)} {mismatch}")

    out = {"rederived": verdicts, "recorded_valid_total":
           sum(1 for r in recorded if r["valid"]), "mismatches": mismatch}
    (ROOT / "experiments" / "claims_audit" / "a1_reaggregate.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[A1] wrote a1_reaggregate.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
