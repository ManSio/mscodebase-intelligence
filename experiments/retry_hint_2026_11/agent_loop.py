"""E69: does following the retry hint recover the withheld neighbours?

Frozen: `frozen/PLAN.md`. For every solvable dev task of the B1 benchmark:

1. call `investigate` with defaults, score it, and look for the `next:` line;
2. if the hint names `include_neighbours=true`, replay with it and score again.

Run: python experiments/retry_hint_2026_11/agent_loop.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EXP / "bench_2026_11"))
sys.path.insert(0, str(EXP / "xerj_2026_11"))
sys.path.insert(0, str(EXP / "xerj_2026_11" / "evidence_gate"))
sys.stdout.reconfigure(encoding="utf-8")

from run import CORPUS, _hits, _kept_gold, _tasks  # noqa: E402
from run_gate import _files, _norm, _tools_for  # noqa: E402
from wilson import wilson  # noqa: E402

HINT_RE = re.compile(r"^next: investigate\((.*)\)$", re.M)


def _has_next(text: str) -> bool:
    return bool(HINT_RE.search(text)) and "include_neighbours=true" in text


def main() -> int:
    tasks = []
    for task in _tasks("dev"):
        gold = _kept_gold(task)
        if gold:
            tasks.append({**task, "gold": gold})
    print(f"dev solvable tasks={len(tasks)}", flush=True)

    tool = _tools_for({CORPUS})[str(CORPUS)]
    rows = []
    for index, task in enumerate(tasks, 1):
        text = asyncio.run(tool.execute(query=task["question"], limit=8,
                                        project_root=str(CORPUS)))
        files = _norm(_files(text), CORPUS)
        hinted = _has_next(text)
        second = []
        if hinted:
            more = asyncio.run(tool.execute(query=task["question"], limit=8,
                                            include_neighbours=True,
                                            project_root=str(CORPUS)))
            second = _norm(_files(more), CORPUS)
        rows.append({
            "id": task["id"],
            "default_top1": _hits(files, task["gold"], 1),
            "default_top5": _hits(files, task["gold"], 5),
            "hinted": hinted,
            "hinted_top1": _hits(second, task["gold"], 1) if hinted else None,
            "hinted_top5": _hits(second, task["gold"], 5) if hinted else None,
        })
        print(f"  {index:>3}/{len(tasks)} {task['id']} "
              f"hint={hinted} default@5={rows[-1]['default_top5']} "
              f"hinted@5={rows[-1]['hinted_top5']}", flush=True)

    def rate(key: str) -> int:
        return sum(1 for r in rows if r[key])

    emitted = sum(1 for r in rows if r["hinted"])
    default5 = rate("default_top5")
    hinted5 = rate("hinted_top5")
    # A hinted task abstained by definition, so its default hit@5 is False; the
    # panel-level result is "default answer + recovered", not "recovered alone".
    assert all(not r["default_top5"] for r in rows if r["hinted"])
    after_total = default5 + hinted5
    lo, hi = wilson(after_total, len(rows))
    print(f"\nhint emitted on {emitted}/{len(rows)} tasks")
    print(f"default hit@5        = {default5}/{len(rows)}  (E68 baseline: 19)")
    print(f"recovered by hint    = {hinted5}/{emitted}")
    print(f"default + hint total = {after_total}/{len(rows)}  "
          f"[{lo:.2f}, {hi:.2f}]  (E68 neighbours arm: 38)")

    preds = {
        "R1 default unchanged (19)": default5 == 19,
        "R2 hint coverage 100% of abstains": emitted >= 36,
        "R3 default+hint >= 36": after_total >= 36,
    }
    print("\nfrozen predictions")
    for label, passed in preds.items():
        print(f"  {label:<34} {'PASS' if passed else 'FAIL'}")

    (HERE / "results.json").write_text(json.dumps(
        {"tasks": len(rows), "emitted": emitted, "default_hit5": default5,
         "recovered_hit5": hinted5, "after_total_hit5": after_total,
         "predictions": preds},
        ensure_ascii=False, indent=1), encoding="utf-8", newline="")
    return 0 if all(preds.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
