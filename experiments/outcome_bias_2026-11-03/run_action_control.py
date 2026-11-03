"""E-OUTCOME-4: does the model separate mild vs severe action with outcome held fixed?"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from run_outcome_bias import ask, parse_digit, system_prompt  # noqa: E402

MODEL = "qwen2.5-3b-instruct"
BASE_URL = "http://localhost:1234/v1"
TRIALS = 5


def main() -> int:
    import httpx

    path = ROOT / "frozen" / "ACTION_CONTROL.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        print("T10: empty", file=sys.stderr)
        return 2

    ask_kw = dict(base_url=BASE_URL, system=system_prompt(9), max_tokens=16, timeout=300, send_reasoning=False)
    cells: dict[str, list[int]] = defaultdict(list)
    raw = []
    total = len(rows) * TRIALS
    done = 0
    for row in rows:
        for trial in range(TRIALS):
            res = ask(httpx, "", MODEL, row["text"], trial, **ask_kw)
            digit = parse_digit(res.get("content", ""), 9) if res.get("ok") else None
            raw.append({"model": MODEL, "case": row["case"], "trial": trial, "ok": res.get("ok"), "content": res.get("content"), "digit": digit, "error": res.get("error")})
            if digit is not None:
                cells[row["case"]].append(digit)
            done += 1
            print(f"[{done}/{total}] {row['case']} t{trial} -> {digit}", flush=True)

    (ROOT / "results" / "raw_e4.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in raw) + "\n", encoding="utf-8")

    parsed = sum(len(v) for v in cells.values())
    if parsed == 0:
        print("T10: zero parsed digits", file=sys.stderr)
        return 2

    def m(xs: list[int]) -> float | None:
        return round(statistics.fmean(xs), 3) if xs else None

    for case in sorted(cells):
        print(f"{case:14s} mean={m(cells[case])} vals={cells[case]}")
    hm, hs = m(cells.get("harm_mild", [])), m(cells.get("harm_severe", []))
    nm, ns = m(cells.get("noharm_mild", [])), m(cells.get("noharm_severe", []))
    print(f"\naction gap WITH harm    (severe - mild): {None if None in (hm, hs) else round(hs - hm, 3)}")
    print(f"action gap WITHOUT harm (severe - mild): {None if None in (nm, ns) else round(ns - nm, 3)}")
    print(f"outcome gap mild   (harm - noharm): {None if None in (hm, nm) else round(hm - nm, 3)}")
    print(f"outcome gap severe (harm - noharm): {None if None in (hs, ns) else round(hs - ns, 3)}")
    print(f"negative control (Elm - Pine): {None if None in (m(cells.get('neg_elm', [])), m(cells.get('neg_pine', []))) else round(m(cells['neg_elm']) - m(cells['neg_pine']), 3)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
