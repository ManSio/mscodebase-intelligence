"""Dry run of the microtask pipeline: no model is called.

It performs every mechanical step that does not need a model:
plan gate -> worktree copy -> Brief construction -> artifact layout.

It also asserts the isolation property that matters most: the worktree and the
Briefs must not contain the frozen experiment inputs or the hidden tests.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from brief_builder import build_brief
from validate_plan import PlanError, validate

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPERIMENT = Path(__file__).resolve().parents[1]
FROZEN = EXPERIMENT / "frozen"
REPO = FROZEN / "repo"
RUNS = EXPERIMENT / "runs"


def assert_no_leak(worktree: Path, briefs: list[str]) -> list[str]:
    problems: list[str] = []
    for path in worktree.rglob("*"):
        rel = path.relative_to(worktree).as_posix().lower()
        if "hidden" in rel or "frozen" in rel or rel.startswith("plans/"):
            problems.append(f"worktree contains forbidden path: {rel}")
    for text in briefs:
        lowered = text.lower()
        for needle in ("hidden/", "frozen/hidden", "test_p1_hidden", "test_p2_hidden"):
            if needle in lowered:
                problems.append(f"brief leaks hidden artifact: {needle}")
    return problems


def dry_run(task_name: str, out_root: Path) -> dict:
    plan_path = FROZEN / "plans" / f"{task_name}.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    decision = validate(plan)
    if decision["mode"] != "microtasks":
        raise PlanError("plan fell back to single_session")

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{task_name}"
    run_dir = out_root / run_id
    worktree = run_dir / "worktree"
    briefs_dir = run_dir / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=False)
    shutil.copytree(REPO, worktree)

    briefs = []
    brief_meta = []
    for task in plan["tasks"]:
        brief = build_brief(task, worktree)
        (briefs_dir / f"{task['id']}.md").write_text(brief.text, encoding="utf-8")
        briefs.append(brief.text)
        brief_meta.append(brief.as_dict())

    problems = assert_no_leak(worktree, briefs)
    if problems:
        raise PlanError("; ".join(problems))

    (run_dir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    meta = {
        "run_id": run_id,
        "task": task_name,
        "mode": "dry-run",
        "model_calls": 0,
        "plan_decision": decision,
        "briefs": brief_meta,
        "worktree": str(worktree),
        "isolation": {
            "hidden_tests_in_worktree": False,
            "frozen_inputs_in_worktree": False,
            "brief_leaks_checked": True,
        },
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


@contextmanager
def temp_out_root():
    with tempfile.TemporaryDirectory(prefix="microtask-dryrun-") as tmp:
        yield Path(tmp)


def selftest() -> int:
    with temp_out_root() as out_root:
        for task_name in ("P1_mean", "P2_money"):
            meta = dry_run(task_name, out_root)
            if meta["model_calls"] != 0:
                print(f"SELSTEST FAIL: {task_name} made model calls")
                return 1
            for brief in meta["briefs"]:
                if brief["bytes"] > 8000:
                    print(f"SELFTEST FAIL: {brief['task_id']} brief is {brief['bytes']} bytes")
                    return 1
            print(
                f"{task_name}: {len(meta['briefs'])} brief(s), "
                f"{[b['bytes'] for b in meta['briefs']]} bytes"
            )
    print("SELFTEST: PASS (dry run, no model calls, no hidden leakage)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="P1_mean")
    parser.add_argument("--out", default=str(RUNS))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    try:
        meta = dry_run(args.task, Path(args.out))
    except (OSError, PlanError, json.JSONDecodeError) as exc:
        print(f"DRY RUN FAILED: {exc}")
        return 2
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

