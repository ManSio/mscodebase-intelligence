"""Determinism guard for the commit-localization benchmark (frozen PLAN).

Ten dev tasks, three repeats each: a rate is only publishable if the per-task
result does not move between runs.

Run: python experiments/bench_2026_11/determinism.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORPUS = Path(r"D:\Project\bench-B")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "xerj_2026_11"))
sys.path.insert(0, str(ROOT / "experiments" / "xerj_2026_11" / "evidence_gate"))
sys.stdout.reconfigure(encoding="utf-8")

from run_gate import _files, _norm, _tools_for  # noqa: E402

from run import _hits  # noqa: E402


def main() -> int:
    tasks = [json.loads(x) for x in (HERE / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    tasks = [t for t in tasks if t["split"] == "dev" and any((CORPUS / g).is_file() for g in t["gold"])][:10]
    tool = _tools_for({CORPUS})[str(CORPUS)]

    seen: dict[str, list] = {}
    for run in range(3):
        for task in tasks:
            text = asyncio.run(tool.execute(query=task["question"], limit=8,
                                            project_root=str(CORPUS)))
            files = _norm(_files(text), CORPUS)
            seen.setdefault(task["id"], []).append(
                (_hits(files, task["gold"], 1), tuple(files[:3]))
            )
        print(f"run {run + 1}/3", flush=True)

    unstable = [k for k, v in seen.items() if len({x[0] for x in v}) > 1]
    print(f"tasks={len(tasks)} unstable_top1={len(unstable)}")
    for key in unstable:
        print("  ", key, seen[key])
    return 1 if unstable else 0


if __name__ == "__main__":
    raise SystemExit(main())
