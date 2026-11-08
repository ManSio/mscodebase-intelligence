"""Re-score stored E1 answers under the corrected rules (§19.2: from raw, not from a verdict).

The first run's summary counted a tool timeout as "found nothing", which would
let a negative task pass by accident. This recomputes from `b_text`, which is
the raw answer of every call, and prints the valid rate (§18).
"""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
rows = json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))


def score(row: dict) -> bool | None:
    text = row["b_text"]
    if '"ok": false' in text[:300] or "Timeout after" in text:
        return None
    files = row["b_full_files"]
    if row["kind"] == "negative":
        return not files
    if row["kind"] == "ambiguity":
        return all(any(g in f for f in files) for g in row["gold"])
    return any(any(g in f for f in files) for g in row["gold"])


out = []
for row in rows:
    row["b_ok2"] = score(row)
    out.append(row)
    flag = {True: "Y", False: "n", None: "-"}[row["b_ok2"]]
    print(f"{row['id']:<4} {row['kind']:<10} A={'Y' if row['a_ok'] else 'n'} "
          f"B={flag} {row['b_elapsed_s']:5.1f}s degraded={row['degraded'] or '-'}")

print()
for kind in ("positive", "ambiguity", "negative"):
    group = [r for r in out if r["kind"] == kind]
    valid = [r for r in group if r["b_ok2"] is not None]
    a = sum(r["a_ok"] for r in group) / len(group)
    b = (sum(bool(r["b_ok2"]) for r in valid) / len(valid)) if valid else float("nan")
    print(f"{kind:<10} n={len(group):<3} valid={len(valid):<3} A={a:.3f} B={b:.3f}")
    if kind == "negative" and valid:
        print(f"{'':<10} said 'no exact match' B="
              f"{sum(r['answered'] for r in valid) / len(valid):.3f}")
    for r in group:
        if r["b_ok2"] is False:
            print(f"   miss {r['id']}: gold={r['gold']} got={r['b_files'][:3]}")

all_valid = [r for r in out if r["b_ok2"] is not None]
a_all = sum(r["a_ok"] for r in out) / len(out)
b_all = (sum(bool(r["b_ok2"]) for r in all_valid) / len(all_valid)) if all_valid else float("nan")
print(f"\noverall    A={a_all:.3f} B={b_all:.3f}  "
      f"({len(out)} asks, {len(all_valid)} valid B answers)")
(HERE / "baseline_rescored.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline=""
)
