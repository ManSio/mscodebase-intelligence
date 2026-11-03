"""Post-run analysis for E-OUTCOME-1/2. Reads raw.jsonl files, prints all metrics."""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent / "results"
STORIES = ["driver", "warehouse", "nurse", "engineer"]


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cells(raw: list[dict]) -> dict[str, dict[str, list[int]]]:
    out: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in raw:
        if r.get("ok") and r.get("digit") is not None:
            out[r["model"]][f"{r['case']}::{r['variant']}"].append(r["digit"])
    return out


def m(xs: list[int]) -> float:
    return round(statistics.fmean(xs), 2)


def main() -> int:
    for tag, scale in (("e1", 9), ("e2", 100)):
        path = ROOT / f"raw_{tag}.jsonl"
        if not path.exists():
            print(f"missing {path}")
            continue
        raw = load(path)
        c = cells(raw)
        errors = sum(1 for r in raw if not r.get("ok"))
        unparsed = sum(1 for r in raw if r.get("ok") and r.get("digit") is None)
        print(f"\n===== {tag.upper()} (scale 0-{scale}) calls={len(raw)} errors={errors} unparsed={unparsed} =====")
        for model in sorted(c):
            mc = c[model]
            print(f"\n-- {model}")
            for cell in sorted(mc):
                print(f"   {cell:28s} mean={m(mc[cell]):7.2f} vals={mc[cell]}")
            # determinism: cells with >1 distinct value
            varied = [cell for cell, vals in mc.items() if len(set(vals)) > 1]
            print(f"   determinism: {len(varied)} of {len(mc)} cells had >1 distinct value")
            # scale-following: values above 9 on a 0-100 prompt
            if scale == 100:
                out_of_9 = {cell: vals for cell, vals in mc.items() if vals and max(vals) <= 9}
                print(f"   scale-following: {len(out_of_9)} of {len(mc)} cells never exceeded 9")
            leak = {}
            for s in STORIES:
                nh = mc.get(f"{s}::no_harm", [])
                hm = mc.get(f"{s}::harm", [])
                if nh and hm:
                    leak[s] = round(m(hm) - m(nh), 2)
            pos = None
            if mc.get("pos_control::mild") and mc.get("pos_control::severe"):
                pos = round(m(mc["pos_control::severe"]) - m(mc["pos_control::mild"]), 2)
            neg = None
            if mc.get("neg_control::a") and mc.get("neg_control::b"):
                neg = round(m(mc["neg_control::a"]) - m(mc["neg_control::b"]), 2)
            thr_pos = 1.0 if scale == 9 else 10.0
            thr_neg = 0.5 if scale == 9 else 5.0
            print(f"   leak={leak}")
            print(f"   pos_gap={pos} (threshold >{thr_pos}: {'PASS' if pos is not None and pos > thr_pos else 'FAIL'})")
            print(f"   neg_delta={neg} (threshold <{thr_neg}: {'PASS' if neg is not None and abs(neg) < thr_neg else 'FAIL'})")
            print(f"   leak direction positive: {sum(1 for v in leak.values() if v > 0)} of {len(leak)} stories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
