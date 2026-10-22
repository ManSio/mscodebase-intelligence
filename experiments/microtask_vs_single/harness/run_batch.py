"""Run a batch of corpus cells sequentially, resumable.

Usage:
    python run_batch.py --list fix|noop|block|all --arms A,C --repeats 1
    python run_batch.py --cells "A:17e65663b7_health,C:17e65663b7_health"

Every cell is a separate process (isolation), progress is appended to
`runs/batch_progress.jsonl`, and cells already recorded are skipped — a batch
can be interrupted and resumed without paying twice.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPERIMENT = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve().parent
RUNS = EXPERIMENT / "runs"
PROGRESS = RUNS / "batch_progress.jsonl"


def corpus_ids() -> list[str]:
    corpus = EXPERIMENT / "frozen" / "corpus"
    ids = sorted(p.stem for p in corpus.glob("*.json") if p.name != "index.json")
    ids += sorted(p.stem for p in (corpus / "specs").glob("*.json"))
    return sorted(set(ids))


def class_of(task_id: str) -> str:
    if task_id.endswith("_noop"):
        return "noop"
    if task_id.endswith("_block"):
        return "block"
    return "fix"


def done_cells() -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    if not PROGRESS.is_file():
        return done
    for line in PROGRESS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        done.add((record.get("arm", ""), record.get("task", "")))
    return done


def run_cell(arm: str, task: str, timeout: int) -> dict:
    started = time.time()
    proc = subprocess.run(
        [sys.executable, str(HARNESS / "run_corpus.py"), "--arm", arm, "--task", task],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    record = {
        "arm": arm,
        "task": task,
        "class": class_of(task),
        "rc": proc.returncode,
        "wall_s": round(time.time() - started, 1),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    result_file = None
    runs = sorted(RUNS.glob(f"{arm}-{task}-*"), key=lambda p: p.stat().st_mtime)
    if runs:
        result_file = runs[-1] / "result.json"
    if result_file and result_file.is_file():
        data = json.loads(result_file.read_text(encoding="utf-8"))
        record.update(
            {
                "run_id": data.get("run_id"),
                "outcome": data.get("outcome"),
                "hidden": (data.get("hidden") or {}).get("verdict"),
                "requests": data.get("proxy_requests"),
                "prompt_max": data.get("prompt_tokens_max"),
                "total_tokens": data.get("total_tokens"),
                "agent_status": data.get("agent_status"),
                "served_by": data.get("served_by"),
            }
        )
    with PROGRESS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", default="all", choices=["fix", "noop", "block", "all"])
    parser.add_argument("--arms", default="A,C")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cells", default="")
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="re-run cells already recorded")
    args = parser.parse_args()

    if args.cells:
        cells = []
        for item in args.cells.split(","):
            arm, task = item.split(":", 1)
            cells.append((arm.strip(), task.strip()))
    else:
        ids = corpus_ids()
        if args.list != "all":
            ids = [i for i in ids if class_of(i) == args.list]
        arms = [a.strip() for a in args.arms.split(",") if a.strip()]
        cells = [(arm, task) for _ in range(args.repeats) for arm in arms for task in ids]

    done = set() if args.force else done_cells()
    todo = [(a, t) for a, t in cells if (a, t) not in done]
    print(f"cells: {len(cells)}  already done: {len(cells) - len(todo)}  to run: {len(todo)}")
    if args.dry_run:
        for arm, task in todo:
            print(f"  {arm} / {task} ({class_of(task)})")
        return 0

    for index, (arm, task) in enumerate(todo, start=1):
        print(f"[{index}/{len(todo)}] {arm} / {task}", flush=True)
        try:
            record = run_cell(arm, task, args.timeout)
        except subprocess.TimeoutExpired:
            record = {"arm": arm, "task": task, "outcome": "batch_timeout", "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            with PROGRESS.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(
            f"    -> {record.get('outcome')} | req={record.get('requests')} "
            f"| tokens={record.get('total_tokens')} | {record.get('wall_s')}s",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

