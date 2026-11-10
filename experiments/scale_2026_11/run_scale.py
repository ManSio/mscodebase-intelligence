"""Run the scale panel (frozen: `frozen/PLAN.md`).

One arm (shipped defaults), N tasks, metrics per bucket plus the calibration
check S3: if the anchors drift from E65, the run is not publishable.

Run:
    python experiments/scale_2026_11/run_scale.py            # full panel
    python experiments/scale_2026_11/run_scale.py --limit 8  # smoke
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EXP / "xerj_2026_11"))
sys.path.insert(0, str(EXP / "xerj_2026_11" / "evidence_gate"))
sys.stdout.reconfigure(encoding="utf-8")

from run_baseline import score as canon_score  # noqa: E402
from run_gate import VERDICT_RE, _files, _invalid, _norm, _tools_for  # noqa: E402
from wilson import wilson  # noqa: E402

TASKS = HERE / "tasks.jsonl"
# Frozen calibration targets from E65 (`fusion/REPORT.md`), weights arm.
ANCHOR_EXPECTED = {"anchor:xerj/positive": 6, "anchor:mcp_audit/positive": 11}


def _load() -> list[dict]:
    tasks = [json.loads(line) for line in TASKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not tasks:
        raise SystemExit("empty panel: run generate.py first")
    return tasks


def _run(tool, task: dict) -> dict:
    started = time.perf_counter()
    text = asyncio.run(
        tool.execute(query=task["question"], limit=8,
                     project_root=task.get("root") or str(ROOT))
    )
    elapsed = time.perf_counter() - started
    files = _norm(_files(text), Path(task.get("root") or ROOT))
    valid = not _invalid(text)
    verdict = VERDICT_RE.search(text)
    return {
        "id": task["id"],
        "bucket": task["bucket"],
        "kind": task["kind"],
        "top1": None if not valid else canon_score(task, files[:1]),
        "any": None if not valid else canon_score(task, files[:8]),
        "valid": valid,
        "chars": len(text),
        "verdict": verdict.group(1) if verdict else "",
        "elapsed_s": round(elapsed, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    tasks = _load()
    if args.limit:
        tasks = tasks[:args.limit]
    print(f"tasks={len(tasks)}", flush=True)

    tools = _tools_for({Path(t.get("root") or ROOT) for t in tasks})
    rows = []
    for index, task in enumerate(tasks, 1):
        root = Path(task.get("root") or ROOT)
        row = _run(tools[str(root)], task)
        rows.append(row)
        print(f"  {index:>3}/{len(tasks)} {row['bucket']:<22} "
              f"top1={row['top1']} any={row['any']} "
              f"{row['verdict'] or '-':<9} {row['chars']:>5}c "
              f"{row['elapsed_s']:5.2f}s", flush=True)

    invalid = sum(1 for r in rows if not r["valid"])
    print(f"\ninvalid runs: {invalid}")

    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["valid"]:
            by_bucket[row["bucket"]].append(row)

    print(f"\n{'bucket':<24} {'n':>3}  {'top1':>4}  {'any':>4}  "
          f"{'chars/top1':>10}  95% CI top1")
    summary = {}
    for bucket in sorted(by_bucket):
        subset = by_bucket[bucket]
        top1 = sum(bool(r["top1"]) for r in subset)
        any8 = sum(bool(r["any"]) for r in subset)
        chars = sum(r["chars"] for r in subset)
        per_correct = chars / top1 if top1 else float("nan")
        lo, hi = wilson(top1, len(subset))
        summary[bucket] = {"n": len(subset), "top1": top1, "any": any8,
                           "chars_per_top1": per_correct}
        print(f"{bucket:<24} {len(subset):>3}  {top1:>4}  {any8:>4}  "
              f"{per_correct:>10.0f}  [{lo:.2f}, {hi:.2f}]")

    preds = {}
    name = summary.get("name")
    neg = summary.get("negative")
    qual = summary.get("qualified")
    if args.limit:
        print("\nSMOKE: no predictions, no results.json")
        return 0
    if name:
        preds["S1 name top1 >= 0.60"] = (name["top1"] / name["n"]) >= 0.60
    if neg:
        preds["S2 negatives empty >= 0.95"] = (neg["top1"] / neg["n"]) >= 0.95
    drift = {b: summary.get(b, {}).get("top1") for b in ANCHOR_EXPECTED}
    preds["S3 anchors within +/-2"] = all(
        drift[b] is not None and abs(drift[b] - ANCHOR_EXPECTED[b]) <= 2
        for b in ANCHOR_EXPECTED
    )
    if name and qual:
        preds["S4 qualified <= name"] = (qual["top1"] / qual["n"]) <= (name["top1"] / name["n"])

    print("\nfrozen predictions")
    for label, passed in preds.items():
        print(f"  {label:<32} {'PASS' if passed else 'FAIL'}")

    out = HERE / "results.json"
    if len(tasks) == len(_load()):
        out.write_text(json.dumps({
            "panel": TASKS.name,
            "tasks": len(tasks),
            "invalid": invalid,
            "summary": summary,
            "predictions": preds,
        }, ensure_ascii=False, indent=1), encoding="utf-8", newline="")

    if invalid or not preds.get("S3 anchors within +/-2", False):
        print("ABORT: instrument is not calibrated (S3) or a task did not run.")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
