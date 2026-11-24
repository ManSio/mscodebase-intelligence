"""Compare repeated runs of the same frozen inputs: is the harness deterministic?"""
from __future__ import annotations

import re
import sys
from pathlib import Path

LINE = re.compile(
    r"\[\s*(?P<i>\d+)/\d+\]\s+(?P<id>\S+) A=(?P<at>\d+)tok/(?P<ah>hit|miss) "
    r"C=(?P<ct>\d+)tok/(?P<ch>hit|miss) B=(?P<bt>\d+)tok/(?P<bh>hit|miss)"
)


def _read_text(path: Path) -> str:
    """PowerShell `Tee-Object` writes UTF-16LE; the repo wants UTF-8. Handle both."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if "\x00" not in text:
            return text
    return raw.decode("utf-8", errors="replace")


def parse(path: Path) -> dict:
    out = {}
    for line in _read_text(path).splitlines():
        m = LINE.search(line)
        if m:
            out[m["id"]] = {
                "A": (int(m["at"]), m["ah"]), "C": (int(m["ct"]), m["ch"]),
                "B": (int(m["bt"]), m["bh"]),
            }
    return out


def main() -> int:
    logs = [Path(p) for p in sys.argv[1:]]
    runs = [parse(p) for p in logs]
    ids = sorted(set(runs[0]) & set(runs[-1]))
    diffs = {"A": [], "C": [], "B": []}
    for qid in ids:
        for arm in "ACB":
            base = runs[0][qid][arm]
            for k, run in enumerate(runs[1:], start=2):
                cur = run.get(qid, {}).get(arm)
                if cur is None:
                    continue  # a run that died mid-way is not a difference
                if cur != base:
                    diffs[arm].append({
                        "id": qid, "run": k, "before": base, "after": cur,
                        "delta_tokens": cur[0] - base[0],
                    })
    for arm in "ACB":
        d = diffs[arm]
        cases = {x["id"] for x in d}
        span = max((abs(x["delta_tokens"]) for x in d), default=0)
        print(f"{arm}: keys={len(ids)} differing_cells={len(d)} distinct_cases={len(cases)} "
              f"max_abs_delta_tokens={span} "
              f"hit-flips={sum(1 for x in d if x['before'][1] != x['after'][1])}")
        for x in d[:8]:
            print(f"   {x['id']} run{x['run']}: {x['before']} -> {x['after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
