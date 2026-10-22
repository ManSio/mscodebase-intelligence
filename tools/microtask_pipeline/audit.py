"""Audit one real module with the live pipeline (protocol §22.4).

    python tools/microtask_pipeline/audit.py --repo <copy> --source src/x.py \
        --test tests/test_x.py --task "symptom text"

The audit is machine-verified: the pipeline measures the acceptance command
before and after, and the verdict comes from the exit code plus the artifact
hash — never from the model's claim. Prints the step log, the receipt and the
diff between the pristine copy and the audited file.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import Executor, run_task  # noqa: E402
from mcp_server import make_pristine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="the copy to audit (not the working tree)")
    parser.add_argument("--source", required=True, help="the production file to change")
    parser.add_argument("--test", required=True, help="the test file that must pass")
    parser.add_argument("--task", required=True, help="symptom-level description of the defect")
    parser.add_argument("--executor", default="lmstudio")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    source = Path(args.source).as_posix()
    test = Path(args.test).as_posix()

    pristine = make_pristine(repo, repo.parent / "pristine")

    executor = Executor(backend=args.executor)
    payload = run_task(
        args.task,
        repo,
        pristine,
        executor,
        pairs=[(source, test)],
    )

    print("=" * 78)
    print(f"executor: {executor.backend} / {executor.model}")
    print(f"model calls: {payload.get('executor_calls')}  "
          f"prompt tokens: {payload.get('prompt_tokens')}  "
          f"completion: {payload.get('completion_tokens')}  "
          f"wall: {payload.get('wall_s')}s")
    print("-" * 78)
    print("STEP LOG")
    for step in payload.get("step_log", []):
        print(f"  {step.get('kind'):<12} tool={step.get('tool') or '-':<12} ok={step.get('ok')} "
              f"status={step.get('answer_status')}")
        if step.get("error"):
            print(f"      error: {step['error']}")
        if step.get("observation"):
            print(f"      model: {str(step['observation'])[:200]}")
    print("-" * 78)
    print("RECEIPTS")
    for receipt in payload.get("receipts", []):
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    print("-" * 78)
    print(f"violations: {payload.get('violations')}")

    before = (pristine / source).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    after_path = repo / source
    after = after_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if before != after:
        print("-" * 78)
        print("DIFF (pristine -> audited)")
        print("".join(difflib.unified_diff(before, after, fromfile=f"a/{source}", tofile=f"b/{source}")))
    else:
        print("DIFF: the file was not changed")

    verdict = "PASS" if payload.get("status") == "done" else "FAIL"
    print("=" * 78)
    print(f"AUDIT VERDICT: {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
