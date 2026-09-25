# -*- coding: utf-8 -*-
"""E17 merge: validate shard answer files and rebuild e17_pilot_answers.json.

Expected (id, mode) pairs come from e17_pilot_data.json. Every pair must be
present exactly once; missing/extra/duplicate entries fail loudly.
"""
import sys
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
SHARDS = ROOT / "experiments/bootstrap/e17_shards"


def main() -> int:
    data = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_data.json").read_text(encoding="utf-8")
    )
    expected = {(f["id"], m) for f in data["functions"] for m in f["modes"]}

    found: dict = {}
    dupes = []
    for path in sorted(SHARDS.glob("shard_*.answers.json")):
        items = json.loads(path.read_text(encoding="utf-8"))
        for it in items:
            key = (it["id"], it["mode"])
            if key in found:
                dupes.append((path.name, key))
            found[key] = it["answer"]
        print(f"{path.name}: {len(items)} items")

    missing = sorted(expected - set(found))
    extra = sorted(set(found) - expected)
    print(f"\nexpected={len(expected)} found={len(found)} duplicates={len(dupes)}")
    print(f"missing={missing}")
    print(f"extra={extra}")
    if missing or extra or dupes:
        print("MERGE: FAILED")
        return 1

    answers = []
    for f in data["functions"]:
        modes = {}
        for mode, mdata in f["modes"].items():
            modes[mode] = {
                "answer": found[(f["id"], mode)],
                "tests": mdata["tests"],
            }
        answers.append({
            "id": f["id"],
            "name": f["name"],
            "file_path": f["file_path"],
            "question": f["question"],
            "modes": modes,
        })

    out = {"metadata": data["metadata"], "answers": answers}
    (ROOT / "experiments/bootstrap/e17_pilot_answers.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nwrote e17_pilot_answers.json: {len(answers)} functions, "
          f"{sum(len(a['modes']) for a in answers)} answers")
    print("MERGE: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
