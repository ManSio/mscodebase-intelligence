"""Live smoke test of the pipeline against the owner's LM Studio server.

Uses the frozen corpus task `17e65663b7_health` (a real bug from our history):
the snapshot is the parent of the fix commit, the hidden test is the module's
own test file. Nothing is paid for: the executor is the owner's own GPU.

    python pipeline/live_smoke.py --task 17e65663b7_health
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))

from corpus_tasks import load_task, prepare  # noqa: E402
from engine import Executor, run_task  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="17e65663b7_health")
    parser.add_argument("--backend", default="lmstudio")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    task = load_task(args.task)
    root = Path(tempfile.mkdtemp(prefix="live-pipeline-"))
    worktree = root / "worktree"
    prepare(task, worktree)
    pristine = root / "pristine"
    if not pristine.is_dir():
        shutil.copytree(worktree, pristine)

    executor = Executor(backend=args.backend)
    print(f"task: {args.task}  backend: {args.backend}  model: {executor.model}")
    print(f"repo: {worktree}")

    payload = run_task(
        task.text,
        worktree,
        pristine,
        executor,
        pairs=[(task.src_file, task.test_file)],
    )
    print()
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
    if args.keep:
        print(f"\nkept: {root}")
    else:
        shutil.rmtree(root, ignore_errors=True)
    return 0 if payload.get("status") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
