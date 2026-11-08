"""Re-derive the hidden verdict of finished corpus runs from their worktrees.

No model is called. The verdict is recomputed from the preserved worktree with
the CURRENT evaluation code, and the previous value is kept in the artifact
(`corrected_from`) so the history stays visible (§19.2: never reuse a recorded
verdict as input; re-derive it and then compare).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from corpus_tasks import hidden_verdict, load_task

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPERIMENT = Path(__file__).resolve().parents[1]
RUNS = EXPERIMENT / "runs"
WORKTREE_ROOT = Path(
    os.environ.get(
        "MSC_MICROTASK_WORKTREE_ROOT", str(EXPERIMENT.parents[2] / "mscodebase-microtask-runs")
    )
)


def main() -> int:
    changed = 0
    checked = 0
    for result_file in sorted(RUNS.glob("*/result.json")):
        data = json.loads(result_file.read_text(encoding="utf-8"))
        if "hidden" not in data or not data.get("hidden"):
            continue
        run_id = data.get("run_id", "")
        worktree = WORKTREE_ROOT / run_id / "worktree"
        if not worktree.is_dir():
            continue
        try:
            task = load_task(data["task"])
        except FileNotFoundError:
            continue
        verdict = hidden_verdict(task, worktree, data.get("agent_status", "none"))
        checked += 1
        previous = data["hidden"].get("verdict")
        if previous == verdict["verdict"]:
            continue
        data["hidden"] = verdict
        data["outcome"] = verdict["verdict"]
        data["corrected_from"] = {
            "outcome": previous,
            "reason": data.get("hidden", {}).get("reason"),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "why": "verdict re-derived from the worktree with the current evaluation code",
        }
        result_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        changed += 1
        print(f"  {run_id}: {previous} -> {verdict['verdict']}  ({verdict['reason']})")
    print(f"\nre-evaluated {checked} runs, corrected {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

