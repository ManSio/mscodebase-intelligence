"""Validate a microtask plan before any worker is started.

The planner proposes; this compiler decides. It is intentionally conservative:
a plan that cannot be executed within the frozen limits is rejected, not
"repaired" by guessing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_TASKS = 8
MAX_STEPS = 5
ALLOWED_FALLBACK = {"single_session"}


class PlanError(ValueError):
    pass


def _fail(msg: str) -> None:
    raise PlanError(msg)


def _is_test_path(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    return p.startswith("tests/") or "/tests/" in p or p.startswith("test_") or "/test_" in p


def _check_path(path: str) -> None:
    if not isinstance(path, str) or not path.strip():
        _fail("file path must be a non-empty string")
    p = Path(path)
    if p.is_absolute():
        _fail(f"absolute path is not allowed: {path}")
    if ".." in p.parts:
        _fail(f"parent traversal is not allowed: {path}")
    if _is_test_path(path):
        _fail(f"test file is not allowed in files: {path}")


def _check_task(task: dict) -> None:
    if not isinstance(task, dict):
        _fail("each task must be an object")
    required = {"id", "goal", "symbol", "files", "depends_on", "acceptance", "max_steps"}
    missing = required - set(task)
    if missing:
        _fail(f"task missing fields: {sorted(missing)}")
    if not isinstance(task["id"], str) or not task["id"].strip():
        _fail("task id must be a non-empty string")
    if not isinstance(task["goal"], str) or not task["goal"].strip():
        _fail(f"{task['id']}: goal must be a non-empty string")
    if not isinstance(task["symbol"], str) or not task["symbol"].strip():
        _fail(f"{task['id']}: symbol must be a non-empty string")
    files = task["files"]
    if not isinstance(files, list) or len(files) != 1:
        _fail(f"{task['id']}: exactly one file per microtask is required")
    _check_path(files[0])
    deps = task["depends_on"]
    if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
        _fail(f"{task['id']}: depends_on must be a list of task ids")
    if task["id"] in deps:
        _fail(f"{task['id']}: task cannot depend on itself")
    acceptance = task["acceptance"]
    if not isinstance(acceptance, str) or not acceptance.strip():
        _fail(f"{task['id']}: acceptance is required")
    if "hidden" in acceptance.lower():
        _fail(f"{task['id']}: hidden tests cannot be an acceptance command")
    steps = task["max_steps"]
    if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= MAX_STEPS:
        _fail(f"{task['id']}: max_steps must be an integer in 1..{MAX_STEPS}")


def validate(plan: object) -> dict:
    if not isinstance(plan, dict):
        _fail("plan must be a JSON object")
    if "fallback" in plan:
        if plan["fallback"] not in ALLOWED_FALLBACK:
            _fail(f"unknown fallback: {plan['fallback']!r}")
        if plan.get("tasks"):
            _fail("fallback plan must not contain tasks")
        return {"mode": "fallback", "reason": plan["fallback"], "tasks": []}

    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        _fail("tasks must be a non-empty list")
    if len(tasks) > MAX_TASKS:
        _fail(f"too many microtasks: {len(tasks)} > {MAX_TASKS}")

    ids = set()
    owners: dict[str, str] = {}
    for task in tasks:
        _check_task(task)
        tid = task["id"]
        if tid in ids:
            _fail(f"duplicate task id: {tid}")
        ids.add(tid)
        path = task["files"][0].replace("\\", "/")
        if path in owners:
            _fail(f"two writers for {path}: {owners[path]} and {tid}")
        owners[path] = tid

    for task in tasks:
        for dep in task["depends_on"]:
            if dep not in ids:
                _fail(f"{task['id']}: unknown dependency {dep}")

    graph = {t["id"]: list(t["depends_on"]) for t in tasks}
    state: dict[str, int] = {}

    def visit(node: str) -> None:
        if state.get(node) == 1:
            _fail(f"dependency cycle at {node}")
        if state.get(node) == 2:
            return
        state[node] = 1
        for nxt in graph[node]:
            visit(nxt)
        state[node] = 2

    for tid in graph:
        visit(tid)

    return {"mode": "microtasks", "tasks": [t["id"] for t in tasks], "files": sorted(owners)}


def _valid_plan() -> dict:
    return {
        "tasks": [
            {
                "id": "T1",
                "goal": "round money half up",
                "symbol": "tinycalc.core.round_money",
                "files": ["tinycalc/core.py"],
                "depends_on": [],
                "acceptance": "python -m pytest tests/test_public.py::test_round_money_basic -q",
                "max_steps": 3,
            },
            {
                "id": "T2",
                "goal": "format totals with round_money",
                "symbol": "tinycalc.formatting.format_total",
                "files": ["tinycalc/formatting.py"],
                "depends_on": ["T1"],
                "acceptance": "python -m pytest tests/test_public.py::test_total_half_up -q",
                "max_steps": 3,
            },
        ]
    }


def _invalid_plans() -> list[tuple[str, dict]]:
    base = _valid_plan()
    cases = []

    p = json.loads(json.dumps(base))
    p["tasks"][0]["files"] = ["tinycalc/core.py", "tinycalc/formatting.py"]
    cases.append(("two files in one task", p))

    p = json.loads(json.dumps(base))
    p["tasks"][0]["depends_on"] = ["T2"]
    cases.append(("dependency cycle", p))

    p = json.loads(json.dumps(base))
    del p["tasks"][0]["acceptance"]
    cases.append(("missing acceptance", p))

    p = json.loads(json.dumps(base))
    p["tasks"][1]["files"] = ["tests/test_public.py"]
    cases.append(("test file", p))

    p = json.loads(json.dumps(base))
    p["tasks"][1]["files"] = ["tinycalc/core.py"]
    cases.append(("two writers", p))

    p = json.loads(json.dumps(base))
    p["tasks"][1]["depends_on"] = ["T9"]
    cases.append(("unknown dependency", p))

    return cases


def selftest() -> int:
    result = validate(_valid_plan())
    if result["mode"] != "microtasks" or result["tasks"] != ["T1", "T2"]:
        print("SELFTEST FAIL: valid plan was not accepted")
        return 1

    for name, plan in _invalid_plans():
        try:
            validate(plan)
        except PlanError:
            continue
        print(f"SELFTEST FAIL: invalid plan accepted: {name}")
        return 1

    fallback = validate({"fallback": "single_session", "tasks": []})
    if fallback["mode"] != "fallback":
        print("SELFTEST FAIL: fallback rejected")
        return 1

    print("SELFTEST: PASS (valid accepted; 6 invalid rejected; fallback accepted)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", nargs="?", help="path to plan.json")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.plan:
        parser.error("plan path or --selftest is required")

    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        result = validate(plan)
    except (OSError, json.JSONDecodeError, PlanError) as exc:
        print(f"REJECT: {exc}")
        return 2

    print(json.dumps({"status": "ACCEPT", **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

