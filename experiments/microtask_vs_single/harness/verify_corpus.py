"""Validate the corpus mechanically, without a model.

For every task:

* **fix** — the hidden test ids must FAIL on the snapshot (the bug is really
  there) and PASS after the real fix is applied (the task is solvable and the
  test is the right one);
* **no-op** — the hidden test must already PASS on the snapshot (the behaviour
  already holds, so "change nothing" is the right answer) and the target file
  must be byte-identical to the fix commit;
* **block** — the referenced test file must NOT exist in the snapshot (the
  specification is genuinely missing).

A corpus that does not satisfy these is not a corpus; the exit code is 2.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from corpus_tasks import REPO, list_tasks, load_task, prepare, run_pytest, sha256_normalized

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEMP = Path(__import__("tempfile").gettempdir()) / "microtask-corpus-verify"


def git_show(sha: str, path: str) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{sha}:{path}"], cwd=str(REPO), capture_output=True, timeout=120
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git show {sha}:{path} failed")
    return proc.stdout


def main() -> int:
    TEMP.mkdir(parents=True, exist_ok=True)
    rows = []
    failures = []
    for task_id in list_tasks():
        task = load_task(task_id)
        worktree = TEMP / task_id / "worktree"
        if worktree.exists():
            subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(worktree)], capture_output=True)
        worktree.mkdir(parents=True)
        prepare(task, worktree)

        if task.cls == "fix":
            before_rc, before_out = run_pytest(worktree, task.test_file, task.fail_to_pass)
            fix_sha = FIX_SHA[task_id]
            for rel in task.src_files:
                src = worktree / rel
                src.parent.mkdir(parents=True, exist_ok=True)
                src.write_bytes(git_show(fix_sha, rel))
            after_rc, after_out = run_pytest(worktree, task.test_file, task.fail_to_pass)
            ok = before_rc != 0 and after_rc == 0
            detail = f"before_rc={before_rc} after_rc={after_rc}"
        elif task.cls == "no-op":
            rc, out = run_pytest(worktree, task.test_file, task.hidden_test_ids or [])
            unchanged = True
            if task.unchanged_file:
                path = worktree / task.unchanged_file
                unchanged = path.is_file() and sha256_normalized(path.read_bytes()) == task.unchanged_sha
            ok = rc == 0 and unchanged
            detail = f"rc={rc} unchanged={unchanged}"
        else:  # block
            exists = (worktree / (task.missing_test or "")).exists()
            ok = not exists
            detail = f"missing_test_exists={exists}"

        rows.append((task_id, task.cls, "PASS" if ok else "FAIL", detail))
        if not ok:
            failures.append(task_id)

    print(f"{'task':<44} {'class':<7} {'control':<7} detail")
    print("-" * 100)
    for row in rows:
        print(f"{row[0]:<44} {row[1]:<7} {row[2]:<7} {row[3]}")

    print()
    print(f"tasks: {len(rows)}   control failures: {len(failures)}")
    if failures:
        print("REFUSE: corpus control failed for:", ", ".join(failures))
        return 2
    print("CORPUS CONTROL: PASS (every task has a verified negative and positive side)")
    return 0


FIX_SHA: dict[str, str] = {}


def load_fix_shas() -> None:
    corpus = Path(__file__).resolve().parents[1] / "frozen" / "corpus"
    for path in corpus.glob("*.json"):
        if path.name == "index.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        FIX_SHA[data["task_id"]] = data["fix_sha"]


if __name__ == "__main__":
    load_fix_shas()
    raise SystemExit(main())


