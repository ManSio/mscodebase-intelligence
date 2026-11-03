"""E-OUTCOME-7: 2x2 with unambiguous severity + negative control, local exact readout."""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from run_exact_readout import local_expected  # noqa: E402

TAG = "e7"


def main() -> int:
    import httpx

    rows = [json.loads(l) for l in (ROOT / "frozen" / "STORIES-7.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    pairs = [s for s in rows if s["group"] == "pair"]
    neg = next((s for s in rows if s["group"] == "neg"), None)
    if not pairs:
        print("T10: empty story set", file=sys.stderr)
        return 2

    cells = []
    for s in pairs:
        for action in ("mild", "severe"):
            for outcome in ("no_harm", "harm"):
                cells.append({"case": s["id"], "action": action, "outcome": outcome, "name": s["name"],
                              "body": s[f"{action}_action"] + " " + s[outcome]})
    if neg:
        cells.append({"case": "neg_control", "action": "a", "outcome": "fixed", "name": neg["name"], "body": neg["variant_a"]})
        cells.append({"case": "neg_control", "action": "b", "outcome": "fixed", "name": neg["name"], "body": neg["variant_b"]})

    raw = []
    for cell in cells:
        res = local_expected(httpx, cell)
        raw.append({"model": "qwen2.5-3b-instruct", "case": cell["case"], "action": cell["action"],
                    "outcome": cell["outcome"], **res})
        print(f"{cell['case']}/{cell['action']}/{cell['outcome']}: ok={res.get('ok')} "
              f"blame={None if not res.get('ok') else round(res['blame'], 3)} "
              f"mass={None if not res.get('ok') else round(res['mass'], 3)}", flush=True)

    (ROOT / "results" / f"raw_{TAG}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in raw) + "\n", encoding="utf-8")

    parsed = [r for r in raw if r.get("ok") and r.get("blame") is not None]
    if not parsed:
        print("T10: zero parsed reads", file=sys.stderr)
        return 2
    t = {(r["case"], r["action"], r["outcome"]): r for r in parsed}

    out_rows = []
    print("\n=== metrics ===")
    for s in pairs:
        def g(a, o):
            r = t.get((s["id"], a, o))
            return r["blame"] if r else None
        mn, sn, mh, sh = g("mild", "no_harm"), g("severe", "no_harm"), g("mild", "harm"), g("severe", "harm")
        if None in (mn, sn, mh, sh):
            print(f"  {s['id']}: incomplete")
            continue
        gap_n = sn - mn
        gap_h = sh - mh
        collapse = round(1 - gap_h / gap_n, 3) if gap_n > 0.5 else None
        masses = [t[(s["id"], a, o)]["mass"] for a in ("mild", "severe") for o in ("no_harm", "harm")
                  if (s["id"], a, o) in t]
        row = {"story": s["id"], "mild_noharm": round(mn, 3), "severe_noharm": round(sn, 3),
               "mild_harm": round(mh, 3), "severe_harm": round(sh, 3),
               "action_gap_noharm": round(gap_n, 3), "action_gap_harm": round(gap_h, 3),
               "collapse": collapse, "outcome_gap_mild": round(mh - mn, 3),
               "min_mass": round(min(masses), 3)}
        out_rows.append(row)
        print(f"  {json.dumps(row, ensure_ascii=False)}")

    neg_delta = None
    if ("neg_control", "a", "fixed") in t and ("neg_control", "b", "fixed") in t:
        neg_delta = round(t[("neg_control", "a", "fixed")]["blame"] - t[("neg_control", "b", "fixed")]["blame"], 3)
        print(f"  negative control delta: {neg_delta}")

    print("\n=== summary ===")
    print("  H1 action readable (gap>0.5):", sum(1 for r in out_rows if r["action_gap_noharm"] > 0.5), "of", len(out_rows))
    print("  H2 outcome dominates (outcome_gap>action_gap):", sum(1 for r in out_rows if r["outcome_gap_mild"] > r["action_gap_noharm"]), "of", len(out_rows))
    print("  H3 min mass:", min((r["min_mass"] for r in out_rows), default=None))
    print("  H4 neg delta:", neg_delta)
    print("  H5 collapse where baseline>0.5:", [(r["story"], r["collapse"]) for r in out_rows if r["collapse"] is not None])
    (ROOT / "results" / f"aggregate_{TAG}.json").write_text(
        json.dumps({"rows": out_rows, "neg_delta": neg_delta}, indent=2, ensure_ascii=False), encoding="utf-8")
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
