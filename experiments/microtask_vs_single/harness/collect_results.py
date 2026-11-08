"""Collect the pilot results from the run artifacts.

Rules this collector obeys, and why:

1. **Refuse to print a score when a control fails.** The hidden-test instrument
   is validated by `selftest_frozen.py` (negative control must fail, positive
   control must pass). If that control is not green, the numbers below would be
   quoted from an unvalidated instrument — so nothing is printed and the exit
   code is 2.
2. **Refuse to print an empty table.** A rate or a table over an empty
   population is a silent zero; the collector exits 2 instead.
3. **Report the floor and the partition, not only the total.** One run per cell
   is a smoke test, not a validation, and run-to-run movement can exceed the
   gap being reported. Cells with a single run are flagged as such.
4. **Re-derive every number from the raw run directories.** Recorded verdicts
   are never reused as input; runs that do not satisfy the current protocol are
   listed as superseded.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPERIMENT = Path(__file__).resolve().parents[1]
RUNS = EXPERIMENT / "runs"
HARNESS = EXPERIMENT / "harness"


def control_is_green() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, str(HARNESS / "selftest_frozen.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def current_corpus_ids() -> set[str]:
    """Task ids that exist in the current corpus (a withdrawn task is not data)."""
    corpus = EXPERIMENT / "frozen" / "corpus"
    ids = {p.stem for p in corpus.glob("*.json") if p.name != "index.json"}
    ids |= {p.stem for p in (corpus / "specs").glob("*.json")}
    return ids


def load_runs() -> tuple[list[dict], list[dict]]:
    valid: list[dict] = []
    superseded: list[dict] = []
    corpus_ids = current_corpus_ids()
    for run_dir in sorted(RUNS.iterdir()):
        result_file = run_dir / "result.json"
        if not result_file.is_file():
            continue
        data = json.loads(result_file.read_text(encoding="utf-8"))
        arm = data.get("arm")
        if arm not in {"A", "D", "C"}:
            continue
        evaluation = data.get("evaluation") or {}
        hidden = data.get("hidden") or {}
        if "hidden" in data:
            # corpus run: the verdict lives in `hidden`
            record = {
                "run_id": data["run_id"],
                "arm": arm,
                "transport": data.get("transport", "proxy"),
                "task": data["task"],
                "corpus": True,
                "outcome": data.get("outcome"),
                "started_at": data.get("started_at"),
                "finished_at": data.get("finished_at"),
                "hidden_scoped_rc": 0 if hidden.get("verdict") == "pass" else 1,
                "passed": hidden.get("verdict") == "pass",
                "hidden_reason": hidden.get("reason"),
                "agent_status": data.get("agent_status"),
                "plan_tasks": data.get("plan_tasks"),
                "planner_usage": data.get("planner_usage"),
                "proxy_requests": data.get("proxy_requests"),
                "served_by": data.get("served_by"),
                "prompt_tokens_max": data.get("prompt_tokens_max"),
                "total_tokens": data.get("total_tokens"),
                "changed_files": [],
            }
            if data["task"] not in corpus_ids:
                record["withdrawn"] = "task no longer in the current corpus"
                superseded.append(record)
                continue
            valid.append(record)
            continue
        protocol_ok = (
            "hidden_scoped_rc" in evaluation
            and data.get("agents_md_in_ancestors") == []
            and data.get("outcome") not in {None, "unknown"}
        )
        record = {
            "run_id": data["run_id"],
            "arm": arm,
            "transport": data.get("transport", "proxy"),
            "task": data["task"],
            "corpus": False,
            "outcome": data.get("outcome"),
            "started_at": data.get("started_at"),
            "finished_at": data.get("finished_at"),
            "hidden_scoped_rc": evaluation.get("hidden_scoped_rc"),
            "hidden_full_rc": evaluation.get("hidden_full_rc"),
            "public_rc": evaluation.get("public_rc"),
            "passed": evaluation.get("hidden_scoped_rc") == 0,
            "changed_files": data.get("changed_files", []),
            "out_of_scope_files": data.get("out_of_scope_files", []),
            "scope_violations": data.get("scope_violations", []),
            "agents_md_in_ancestors": data.get("agents_md_in_ancestors"),
            "usage": data.get("usage"),
            "planner_usage": data.get("planner_usage"),
            "proxy_requests": data.get("proxy_requests"),
            "worker_usage": data.get("worker_usage"),
        }
        (valid if protocol_ok else superseded).append(record)
    return valid, superseded


def wall_seconds(record: dict) -> float | None:
    try:
        start = datetime.fromisoformat(record["started_at"])
        end = datetime.fromisoformat(record["finished_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return round((end - start).total_seconds(), 1)


def summarise(record: dict) -> dict:
    usage = record.get("usage") or {}
    totals = usage.get("totals") or {}
    worker = record.get("worker_usage") or []
    worker_prompt = [u["usage"]["prompt_tokens"] for u in worker if u.get("usage")]
    worker_total = [u["usage"]["total_tokens"] for u in worker if u.get("usage")]
    modes = sorted({(u.get("tirtha") or {}).get("mode") for u in worker if u.get("tirtha")})
    served = sorted({(u.get("tirtha") or {}).get("served_by") for u in worker if u.get("tirtha")})
    served_models = sorted(
        {(u.get("tirtha") or {}).get("served_model_id") for u in worker if u.get("tirtha")}
    )
    prompt_max = record.get("prompt_tokens_max")
    total = record.get("total_tokens")
    if prompt_max is None:
        prompt_max = max(worker_prompt) if worker_prompt else None
    if total is None:
        total = sum(worker_total) if worker_total else None
    return {
        "run_id": record["run_id"],
        "arm": record["arm"],
        "transport": record["transport"],
        "task": record["task"],
        "corpus": record.get("corpus", False),
        "outcome": record["outcome"],
        "passed": record.get("passed", record.get("hidden_scoped_rc") == 0),
        "wall_s": wall_seconds(record),
        "hidden_scoped_rc": record.get("hidden_scoped_rc"),
        "changed": len(record.get("changed_files", [])),
        "scope_violations": len(record.get("scope_violations", []))
        + len(record.get("out_of_scope_files", [])),
        "planner_requests": (record.get("planner_usage") or {}).get("requests"),
        "baseline_requests": usage.get("requests"),
        "baseline_total_tokens": (totals.get("input") or 0) + (totals.get("output") or 0),
        "baseline_max_input_with_cache": usage.get("max_input_with_cache"),
        "worker_requests": record.get("proxy_requests"),
        "worker_prompt_tokens_max": prompt_max,
        "worker_total_tokens_sum": total,
        "worker_modes": modes,
        "worker_served_by": record.get("served_by") or served,
        "worker_served_model_ids": served_models,
        "agent_status": record.get("agent_status"),
    }


def partition(rows: list[dict]) -> list[dict]:
    """Per task: which arms pass, which disagree. The robust statistic."""
    out: list[dict] = []
    tasks = sorted({r["task"] for r in rows})
    for task in tasks:
        cell_rows = [r for r in rows if r["task"] == task]
        per_arm: dict[str, list[bool]] = {}
        for row in cell_rows:
            per_arm.setdefault(f"{row['arm']}/{row['transport']}", []).append(row["passed"])
        verdicts = {k: (sum(v), len(v)) for k, v in per_arm.items()}
        # A task is CONTESTED when the arms disagree on it: one arm passed at
        # least once while another never passed. (Not "all runs of an arm
        # passed" — that hides a task where one arm was lucky.)
        passed_any = {k: sum(v) > 0 for k, v in per_arm.items()}
        out.append(
            {
                "task": task,
                "arms": verdicts,
                "contested": len(set(passed_any.values())) > 1,
                "single_run_cells": [k for k, v in verdicts.items() if v[1] < 2],
            }
        )
    return out


def class_of(task_id: str) -> str:
    if task_id.endswith("_noop"):
        return "noop"
    if task_id.endswith("_block"):
        return "block"
    if task_id.startswith(("P1_", "P2_")):
        return "synthetic-pilot"
    return "fix"


def class_summary(rows: list[dict]) -> list[dict]:
    out = []
    for cls in ("fix", "noop", "block", "synthetic-pilot"):
        cell_rows = [r for r in rows if class_of(r["task"]) == cls]
        if not cell_rows:
            continue
        for arm in sorted({r["arm"] for r in cell_rows}):
            arm_rows = [r for r in cell_rows if r["arm"] == arm]
            passes = sum(1 for r in arm_rows if r["passed"])
            tokens = [r["worker_total_tokens_sum"] or 0 for r in arm_rows]
            prompts = [r["worker_prompt_tokens_max"] or 0 for r in arm_rows]
            requests = [r["worker_requests"] or 0 for r in arm_rows]
            out.append(
                {
                    "class": cls,
                    "arm": arm,
                    "runs": len(arm_rows),
                    "passed": passes,
                    "tokens_total": sum(tokens),
                    "tokens_max_per_run": max(tokens) if tokens else 0,
                    "prompt_max": max(prompts) if prompts else 0,
                    "requests_max": max(requests) if requests else 0,
                    "outcomes": {
                        o: sum(1 for r in arm_rows if r["outcome"] == o)
                        for o in sorted({r["outcome"] for r in arm_rows})
                    },
                }
            )
    return out


def main() -> int:
    green, control_output = control_is_green()
    if not green:
        print("REFUSE: the hidden-test control is not green, so no score is printed.")
        print(control_output[-1500:])
        return 2

    valid, superseded = load_runs()
    if not valid:
        print("REFUSE: no valid runs in the population; an empty table is not a result.")
        return 2

    rows = [summarise(r) for r in valid]
    rows.sort(key=lambda r: (r["task"], r["arm"], r["transport"], r["run_id"]))

    print("| task | arm/transport | run | outcome | wall_s | hidden_rc | changed | scope_violations | baseline_req | baseline_tokens | worker_req | worker_prompt_max | worker_tokens_sum |")
    print("|" + "---|" * 13)
    for row in rows:
        print(
            f"| {row['task']} | {row['arm']}/{row['transport']} | {row['run_id'][-9:]} | {row['outcome']} | "
            f"{row['wall_s']} | {row['hidden_scoped_rc']} | {row['changed']} | {row['scope_violations']} | "
            f"{row['baseline_requests']} | {row['baseline_total_tokens']} | {row['worker_requests']} | "
            f"{row['worker_prompt_tokens_max']} | {row['worker_total_tokens_sum']} |"
        )

    print()
    print("Floor and partition (the robust statistics):")
    for cell in partition(rows):
        arms = ", ".join(f"{k}={v[0]}/{v[1]}" for k, v in cell["arms"].items())
        flag = ""
        if cell["single_run_cells"]:
            flag = f"  ⚠ single-run cell(s): {', '.join(cell['single_run_cells'])} — smoke test, not validation"
        print(f"  {cell['task']}: {arms}  contested={cell['contested']}{flag}")

    print()
    print("By class (the honest table):")
    for row in class_summary(rows):
        print(
            f"  {row['class']:<16} {row['arm']:<8} runs={row['runs']:<3} passed={row['passed']:<3} "
            f"tokens_total={row['tokens_total']:<10} max_per_run={row['tokens_max_per_run']:<9} "
            f"prompt_max={row['prompt_max']:<7} req_max={row['requests_max']:<4} {row['outcomes']}"
        )

    print()
    print("Tīrtha request metadata (worker arm):")
    for row in rows:
        if row["arm"] != "D" or not row["worker_served_by"]:
            continue
        print(f"  {row['run_id']}: modes={row['worker_modes']} served_by={row['worker_served_by']}")
        print(f"      served_model_ids={row['worker_served_model_ids']}")

    if superseded:
        print()
        print("superseded runs (excluded from the table):")
        for record in superseded:
            print(f"  {record['run_id']} outcome={record['outcome']} (protocol of the current run not met)")

    out = EXPERIMENT / "results_summary.json"
    out.write_text(
        json.dumps(
            {
                "control": "selftest_frozen: PASS",
                "rows": rows,
                "by_class": class_summary(rows),
                "partition": partition(rows),
                "superseded": [r["run_id"] for r in superseded],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

