"""Control/treatment for the evidence gate on frozen panels.

Arms (same commit, same index, one env flag):
  control    MSCODEBASE_EVIDENCE_GATE=0
  treatment  MSCODEBASE_EVIDENCE_GATE=1

The arms are INTERLEAVED per task (control/treatment, then treatment/control,
and so on). Two sequential sweeps would confound the gate with whatever the
host is doing between them: the first run of this harness measured a 12 s
slow-down on six consecutive tasks because a background writer held the index,
and a sequential design would have blamed the gate (2026-11-10).

Panels (read-only):
  XERJ 24      experiments/xerj_2026_11/frozen/benchmark_tasks.md
  mcp_audit 17 experiments/xerj_2026_11/mcp_audit/questions.json

Predictions and kill criteria were frozen in frozen/HYPOTHESES.md before the
first run. Metrics are computed here, not copied from another report.

Run:
    python experiments/xerj_2026_11/evidence_gate/run_gate.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EXP))
sys.stdout.reconfigure(encoding="utf-8")

from run_baseline import parse_tasks, score  # noqa: E402

QUESTIONS = EXP / "mcp_audit" / "questions.json"
ROW_RE = re.compile(r"^(\d+)\. (.+?):(\d+) ", re.M)
VERDICT_RE = re.compile(r"verdict: (\w+)(?: \(([0-9.]+)\))?")


def _files(text: str) -> list[str]:
    rows = ROW_RE.findall(text)
    return [path.replace("\\", "/").lstrip("/") for _, path, _ in rows]


def _norm(files: list[str], root: Path) -> list[str]:
    base = str(root).replace("\\", "/")
    return [f.replace(base, "").lstrip("/") for f in files]


def _invalid(text: str) -> bool:
    head = text[:300]
    return '"ok": false' in head or "Timeout after" in text


def _panel_tasks() -> list[dict]:
    tasks = []
    for task in parse_tasks():
        tasks.append({
            "panel": "xerj",
            "id": task["id"],
            "kind": task["kind"],
            "question": task["question"],
            "gold": task["gold"],
            "root": ROOT,
        })
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    for project, spec in data["projects"].items():
        root = Path(spec["root"])
        for index, (question, gold) in enumerate(
            list(spec.get("questions") or []) + list(spec.get("ru") or []), 1
        ):
            tasks.append({
                "panel": "mcp_audit",
                "id": f"{project[:3].upper()}{index:02d}",
                "kind": "positive",
                "question": question,
                "gold": [gold],
                "root": root,
            })
    return tasks


def _tools_for(roots: set[Path]) -> dict[str, object]:
    from src.core.di_container import (
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )
    from src.mcp.tools.investigate_tool import InvestigateTool

    tools = {}
    for root in roots:
        services = create_service_collection(root)
        services.resolve(ProjectIndexerRegistry).get_indexer(
            root, factory=services.resolve(IndexerFactoryKey)
        )
        tools[str(root)] = InvestigateTool(services)
    return tools


def _run_one(tool, task: dict, arm: str) -> dict:
    os.environ["MSCODEBASE_EVIDENCE_GATE"] = "0" if arm == "control" else "1"
    started = time.perf_counter()
    text = asyncio.run(
        tool.execute(query=task["question"], limit=8, project_root=str(task["root"]))
    )
    elapsed = time.perf_counter() - started
    files = _norm(_files(text), task["root"])
    valid = not _invalid(text)
    verdict = VERDICT_RE.search(text)
    return {
        "arm": arm,
        "panel": task["panel"],
        "id": task["id"],
        "kind": task["kind"],
        "question": task["question"],
        "gold": task["gold"],
        "files": files,
        "top1": None if not valid else score(task, files[:1]),
        "any": None if not valid else score(task, files[:8]),
        "valid": valid,
        "verdict": verdict.group(1) if verdict else "",
        "confidence": float(verdict.group(2)) if verdict and verdict.group(2) else None,
        "elapsed_s": round(elapsed, 3),
        "answered": bool(re.search(r"exact: \w+=0", text)),
        "text": text,
    }


def run_interleaved(
    tasks: list[dict], runs: int = 1
) -> dict[str, list[dict]]:
    tools = _tools_for({task["root"] for task in tasks})
    results: dict[str, list[dict]] = {"control": [], "treatment": []}
    for position, task in enumerate(tasks):
        for run_index in range(runs):
            order = (
                ["control", "treatment"]
                if (position + run_index) % 2 == 0
                else ["treatment", "control"]
            )
            for arm in order:
                row = _run_one(tools[str(task["root"])], task, arm)
                row["run"] = run_index + 1
                results[arm].append(row)
                print(f"  r{run_index + 1} {arm:<9} {task['id']:<5} "
                      f"{task['panel']:<10} top1={row['top1']} any={row['any']} "
                      f"{row['verdict'] or '-':<9} {row['elapsed_s']:5.2f}s")
    return results


def summarise(rows: list[dict]) -> dict:
    """Per-task majority over repeats, the same metric the report quotes.

    Dividing by the number of runs instead would let one repeated tie move the
    rate (review 2026-11-10: mcp_audit read 0.431 in the summary and 0.412 in
    the report while the raw rows were identical).
    """
    summary: dict = {}
    for panel in ("xerj", "mcp_audit"):
        for kind in ("positive", "ambiguity", "negative"):
            subset = [
                r for r in rows
                if r["panel"] == panel and r["kind"] == kind and r["valid"]
            ]
            if not subset:
                continue
            tasks: dict[str, list[dict]] = {}
            for row in subset:
                tasks.setdefault(row["id"], []).append(row)

            def majority(runs: list[dict], key: str) -> bool:
                return sum(bool(run[key]) for run in runs) * 2 > len(runs)

            key = f"{panel}/{kind}"
            summary[key] = {
                "n": len(tasks),
                "runs_per_task": len(subset) // len(tasks),
                "top1": round(
                    sum(majority(t, "top1") for t in tasks.values()) / len(tasks), 3
                ),
                "any": round(
                    sum(majority(t, "any") for t in tasks.values()) / len(tasks), 3
                ),
                "verdicts": {
                    name: sum(t[0]["verdict"] == name for t in tasks.values())
                    for name in ("answer", "caveat", "abstain", "ask_rewrite", "")
                },
            }
            if kind == "negative":
                summary[key]["answered"] = round(
                    sum(majority(t, "answered") for t in tasks.values()) / len(tasks),
                    3,
                )
    times = [r["elapsed_s"] for r in rows if r["valid"]]
    if times:
        summary["latency"] = {
            "n": len(times),
            "mean": round(statistics.mean(times), 3),
            "p95": round(sorted(times)[max(0, int(len(times) * 0.95) - 1)], 3),
        }
    summary["invalid"] = sum(not r["valid"] for r in rows)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="comma-separated task ids")
    parser.add_argument("--runs", type=int, default=3,
                        help="repeats per arm (channel timing is not deterministic)")
    args = parser.parse_args()

    tasks = _panel_tasks()
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        tasks = [t for t in tasks if t["id"] in wanted]
    print(f"tasks: {len(tasks)} "
          f"(xerj {sum(t['panel'] == 'xerj' for t in tasks)}, "
          f"mcp_audit {sum(t['panel'] == 'mcp_audit' for t in tasks)}), "
          f"runs per arm: {args.runs}")

    results = run_interleaved(tasks, args.runs)
    summaries = {}
    for arm, rows in results.items():
        (HERE / f"results_{arm}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1),
            encoding="utf-8", newline="",
        )
        summaries[arm] = summarise(rows)
        (HERE / f"summary_{arm}.json").write_text(
            json.dumps(summaries[arm], ensure_ascii=False, indent=1),
            encoding="utf-8", newline="",
        )

    # Determinism: within the treatment arm, every repeat of a task must give
    # the same verdict and the same first row. With --runs 3 this covers the
    # whole panel, not a four-task sample.
    grouped: dict[str, list[dict]] = {}
    for row in results["treatment"]:
        grouped.setdefault(row["id"], []).append(row)
    unstable = sorted(
        task_id for task_id, rows in grouped.items()
        if len({(r["verdict"], tuple(r["files"][:1])) for r in rows}) > 1
    )
    same = not unstable
    (HERE / "determinism.json").write_text(
        json.dumps({"tasks": len(grouped), "runs_per_task": args.runs,
                    "identical": same, "unstable": unstable},
                   ensure_ascii=False, indent=1),
        encoding="utf-8", newline="",
    )
    print(f"\ndeterminism over {len(grouped)} tasks x {args.runs} runs: "
          f"{'PASS' if same else 'FAIL ' + str(unstable)}")
    print(json.dumps(summaries, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
