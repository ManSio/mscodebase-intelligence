"""E67: does content-aware test-bucket classification fix what it should?

Frozen: `frozen/PLAN.md`. Arms: `path` (shipped) vs `content`, one binary via
`MSCODEBASE_TEST_BUCKET`. Panel: the 3 affected E66 tasks + 41 anchors + 40
sampled positives, 3 repeats, per-task majority.

Run: python experiments/test_bucket_2026_11/run_ab.py
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = HERE.parents[1]
SCALE = EXP / "scale_2026_11"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EXP / "xerj_2026_11"))
sys.path.insert(0, str(EXP / "xerj_2026_11" / "evidence_gate"))
sys.stdout.reconfigure(encoding="utf-8")

from run_baseline import score as canon_score  # noqa: E402
from run_gate import VERDICT_RE, _files, _invalid, _norm, _tools_for  # noqa: E402

AFFECTED = {"risk_level", "module_of", "referenced_modules"}
ARMS = ("path", "content")


def _panel() -> list[dict]:
    rows = [json.loads(x) for x in (SCALE / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    affected, anchors, positives = [], [], []
    for task in rows:
        if task["anchor"]:
            anchors.append(task)
        elif task["id"].startswith("G-N-") and task["id"][4:] in AFFECTED:
            affected.append(task)
        elif task["kind"] == "positive" and not task["anchor"]:
            positives.append(task)
    rng = random.Random(20261110)
    rng.shuffle(positives)
    return affected + anchors + positives[:40]


def _run(tool, task: dict, arm: str) -> dict:
    os.environ["MSCODEBASE_TEST_BUCKET"] = arm
    text = asyncio.run(tool.execute(query=task["question"], limit=8,
                                    project_root=str(task.get("root") or ROOT)))
    files = _norm(_files(text), Path(task.get("root") or ROOT))
    valid = not _invalid(text)
    verdict = VERDICT_RE.search(text)
    return {
        "arm": arm,
        "id": task["id"],
        "top1": None if not valid else canon_score(task, files[:1]),
        "any": None if not valid else canon_score(task, files[:8]),
        "valid": valid,
        "verdict": verdict.group(1) if verdict else "",
    }


def main() -> int:
    tasks = _panel()
    print(f"tasks={len(tasks)} (affected=3 anchors=41 sample=40)", flush=True)
    tool = _tools_for({ROOT})[str(ROOT)]
    results = {arm: [] for arm in ARMS}
    for position, task in enumerate(tasks):
        for run in range(3):
            order = ARMS if (position + run) % 2 == 0 else ARMS[::-1]
            for arm in order:
                row = _run(tool, task, arm)
                results[arm].append(row)

    def majority(rows):
        bits = [r["top1"] for r in rows if r["top1"] is not None]
        return bool(bits) and sum(bits) * 2 > len(bits)

    per_arm = {}
    for arm in ARMS:
        grouped = defaultdict(list)
        for row in results[arm]:
            grouped[row["id"]].append(row)
        per_arm[arm] = {key: {"top1": majority(rows),
                              "any": any(r["any"] for r in rows)}
                        for key, rows in grouped.items()}

    affected = [t["id"] for t in tasks[:3]]
    anchors = [t["id"] for t in tasks[3:44]]
    sample = [t["id"] for t in tasks[44:]]

    def count(arm, key, ids, field="top1"):
        return sum(per_arm[arm][i][field] for i in ids)

    print("\nfrozen predictions")
    t1 = all(per_arm["content"][i]["any"] for i in affected)
    print(f"  T1 affected fixed (any@8): {count('content', '', affected, 'any')}/3 -> "
          f"{'PASS' if t1 else 'FAIL'}")
    t2 = all(per_arm["content"][i]["top1"] >= per_arm["path"][i]["top1"] and
             per_arm["content"][i]["any"] >= per_arm["path"][i]["any"]
             for i in anchors)
    print(f"  T2 anchors not worse: {'PASS' if t2 else 'FAIL'}")
    t3 = all(per_arm["content"][i]["top1"] >= per_arm["path"][i]["top1"] and
             per_arm["content"][i]["any"] >= per_arm["path"][i]["any"]
             for i in sample)
    print(f"  T3 sampled positives not worse: {'PASS' if t3 else 'FAIL'}")
    t4 = all(per_arm["content"][i] == per_arm["path"][i] for i in sample + anchors)
    print(f"  T4 identical on unrelated tasks: {'PASS' if t4 else 'FAIL'}")

    print(f"\n  path    anchors top1={count('path', '', anchors)}/41 "
          f"sample top1={count('path', '', sample)}/40")
    print(f"  content anchors top1={count('content', '', anchors)}/41 "
          f"sample top1={count('content', '', sample)}/40")

    invalid = sum(1 for a in ARMS for r in results[a] if not r["valid"])
    print(f"  invalid runs: {invalid}")
    (HERE / "results.json").write_text(json.dumps(
        {"tasks": len(tasks), "predictions": {"T1": t1, "T2": t2, "T3": t3, "T4": t4},
         "per_arm": per_arm}, ensure_ascii=False, indent=1),
        encoding="utf-8", newline="")
    return 0 if all((t1, t2, t3)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
