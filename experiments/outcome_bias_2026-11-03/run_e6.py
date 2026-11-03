"""E-OUTCOME-6: 2x2 action × outcome, local exact readout."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from run_exact_readout import local_expected  # noqa: E402

TAG = "e6"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retry", action="store_true", help="re-run only failed/missing cells")
    args = ap.parse_args()

    import httpx

    stories = [json.loads(l) for l in (ROOT / "frozen" / "STORIES-6.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if not stories:
        print("T10: empty story set", file=sys.stderr)
        return 2

    cells = []
    for s in stories:
        for action in ("mild", "severe"):
            for outcome in ("no_harm", "harm"):
                cells.append({
                    "case": s["id"],
                    "action": action,
                    "outcome": outcome,
                    "name": s["name"],
                    "body": s[f"{action}_action"] + " " + s[outcome],
                })

    out = ROOT / "results" / f"raw_{TAG}.jsonl"
    previous = {}
    if args.retry and out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                previous[(r["case"], r["action"], r["outcome"])] = r
        print(f"retry mode: {sum(1 for r in previous.values() if r.get('ok'))} ok cells kept")

    raw = []
    for cell in cells:
        key = (cell["case"], cell["action"], cell["outcome"])
        old = previous.get(key)
        if old is not None and old.get("ok") and old.get("blame") is not None:
            raw.append(old)
            continue
        res = local_expected(httpx, cell)
        raw.append({"model": "qwen2.5-3b-instruct", "case": cell["case"], "action": cell["action"],
                    "outcome": cell["outcome"], **res})
        print(f"{cell['case']}/{cell['action']}/{cell['outcome']}: ok={res.get('ok')} "
              f"blame={None if not res.get('ok') else round(res['blame'], 3)} "
              f"mass={None if not res.get('ok') else round(res['mass'], 3)}", flush=True)


    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in raw) + "\n", encoding="utf-8")

    parsed = [r for r in raw if r.get("ok") and r.get("blame") is not None]
    if not parsed:
        print("T10: zero parsed reads", file=sys.stderr)
        return 2
    table = {(r["case"], r["action"], r["outcome"]): r for r in parsed}

    print("\n=== metrics (exact expected blame) ===")
    rows = []
    for s in stories:
        def g(action, outcome):
            r = table.get((s["id"], action, outcome))
            return r["blame"] if r else None
        mn, sn = g("mild", "no_harm"), g("severe", "no_harm")
        mh, sh = g("mild", "harm"), g("severe", "harm")
        masses = [table[(s["id"], a, o)]["mass"] for a in ("mild", "severe") for o in ("no_harm", "harm")
                  if (s["id"], a, o) in table]
        if None in (mn, sn, mh, sh):
            print(f"  {s['id']}: incomplete")
            continue
        gap_noharm = sn - mn
        gap_harm = sh - mh
        collapse = None if abs(gap_noharm) < 1e-9 else 1 - gap_harm / gap_noharm
        outcome_mild = mh - mn
        row = {"story": s["id"], "mild_noharm": round(mn, 3), "severe_noharm": round(sn, 3),
               "mild_harm": round(mh, 3), "severe_harm": round(sh, 3),
               "action_gap_noharm": round(gap_noharm, 3), "action_gap_harm": round(gap_harm, 3),
               "collapse": None if collapse is None else round(collapse, 3),
               "outcome_gap_mild": round(outcome_mild, 3), "min_mass": round(min(masses), 3)}
        rows.append(row)
        print(f"  {json.dumps(row, ensure_ascii=False)}")

    print("\n=== summary ===")
    if rows:
        print("  stories with action_gap_noharm > 0.5:", sum(1 for r in rows if r["action_gap_noharm"] > 0.5), "of", len(rows))
        print("  stories with collapse > 0.5:", sum(1 for r in rows if r["collapse"] is not None and r["collapse"] > 0.5), "of", len(rows))
        print("  stories with outcome > action (no harm):", sum(1 for r in rows if r["outcome_gap_mild"] > r["action_gap_noharm"]), "of", len(rows))
        print("  min digit mass:", min(r["min_mass"] for r in rows))
        print("  mean action gap (no harm):", round(sum(r["action_gap_noharm"] for r in rows) / len(rows), 3))
        print("  mean action gap (harm):   ", round(sum(r["action_gap_harm"] for r in rows) / len(rows), 3))
    (ROOT / "results" / f"aggregate_{TAG}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
