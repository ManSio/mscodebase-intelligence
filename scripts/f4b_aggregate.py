#!/usr/bin/env python3
"""F4b aggregator: per-item / per-condition / per-model summary of a run.

Reproduces the numbers quoted in results/f4b/RESULTS.md from the raw run_*.txt
files. Read-only; prints a report. Controls come from frozen/f4b/manifest.json.

Usage:
    python scripts/f4b_aggregate.py [--results experiments/4A_unit_of_return/results/f4b]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*$")
REPO = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = REPO / "experiments" / "4A_unit_of_return" / "results" / "f4b"
DEFAULT_MANIFEST = REPO / "experiments" / "4A_unit_of_return" / "frozen" / "f4b" / "manifest.json"


def parse(path: Path) -> dict[int, str]:
    m: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        g = ROW.match(line.strip())
        if g and int(g.group(1)) not in m:
            m[int(g.group(1))] = g.group(2).strip()
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(DEFAULT_RESULTS))
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = ap.parse_args()

    man = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    hit = {int(k): v for k, v in man["must_hit"].items()}
    none = [int(n) for n in man["must_none"]]
    root = Path(args.results)

    def clean(a: dict[int, str]) -> str | None:
        for n, exp in hit.items():
            if a.get(n) != exp:
                return f"hit{n}->{a.get(n)}"
        for n in none:
            if a.get(n) != "NONE":
                return f"none{n}->{a.get(n)}"
        return None

    runs = []
    for cond_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for model_dir in sorted(p for p in cond_dir.iterdir() if p.is_dir()):
            for f in sorted(model_dir.glob("run_*.txt")):
                runs.append((cond_dir.name, model_dir.name, f.name, parse(f)))

    print(f"runs={len(runs)}")
    tab: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for cond, model, _, ans in runs:
        tab[(cond, model)][0] += 1
        tab[(cond, model)][1] += int(clean(ans) is None)
    for (cond, model), (n, ok) in sorted(tab.items()):
        print(f"  {cond:8} {model:22} {ok}/{n}")

    print("\nper-item controls:")
    for cond in sorted({c for c, *_ in runs}):
        sub = [a for c, _, _, a in runs if c == cond]
        for n in sorted(list(hit) + none):
            if n in hit:
                k = sum(1 for a in sub if a.get(n) == hit[n])
                print(f"  [{cond}] hit#{n:<2} {k}/{len(sub)}")
            else:
                k = sum(1 for a in sub if a.get(n) == "NONE")
                others = sorted({a.get(n) for a in sub if a.get(n) != "NONE"})
                print(f"  [{cond}] none#{n:<2} {k}/{len(sub)} others={others}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - top-level guard reports and exits non-zero
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
