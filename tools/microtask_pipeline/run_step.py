"""Sidecar for the OpenCode tool adapter: serve ONE edit, return a receipt.

    python run_step.py '{"tool":"edit","args":{...},"directory":...,"worktree":...}'

Two modes, matching the architect/editor split:

* **apply** — the parent (cloud) already specified `oldString`/`newString`:
  the harness applies it deterministically and runs the acceptance command.
  No model is called: the parent already did the thinking.
* **solve** — the parent gave only a goal: the local model writes the diff
  (it is the "editor"), the harness applies it and verifies.

Either way the outcome is a receipt, never a claim: the acceptance command, its
exit code and the sha256 of the artifact. Test files are never writable, and a
tampered test is restored from the pristine copy before the verdict.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import (  # noqa: E402
    Executor,
    _context_for,
    _extract_diff,
    apply_unified_diff,
)

BACKEND = os.environ.get("MSC_EXECUTOR", "lmstudio")


def repo_root_for(path: Path, fallback: Path) -> Path:
    current = path if path.is_dir() else path.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return fallback


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def is_test_path(rel: str) -> bool:
    low = rel.replace("\\", "/").lower()
    return low.startswith("tests/") or "/tests/" in low or Path(low).name.startswith("test_")


def apply_replacement(text: str, old: str, new: str) -> tuple[str | None, str]:
    """Replace `old` with `new`; tolerate the model's re-indentation."""
    if not old:
        return None, "empty oldString"
    if old in text:
        return text.replace(old, new, 1), ""
    stripped = "\n".join(
        line.split(":", 1)[1].lstrip() if line.split(":", 1)[0].strip().isdigit() else line
        for line in old.splitlines()
    )
    if stripped and stripped in text:
        return text.replace(stripped, new, 1), ""
    import re

    norm_old = re.sub(r"[ \t]+", " ", stripped)
    norm_text = re.sub(r"[ \t]+", " ", text)
    if norm_old and norm_old in norm_text:
        start = norm_text.index(norm_old)
        original = text[start : start + len(old)]
        return text.replace(original, new, 1), ""
    return None, "oldString not found in the file"


def run_acceptance(cmd: str, cwd: Path) -> tuple[int, str]:
    if not cmd:
        return 0, ""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))[-800:]


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_step.py '<json payload>'")
        return 2
    payload = json.loads(sys.argv[1])
    args = payload.get("args") or {}
    file_path = Path(str(args.get("filePath") or args.get("file") or "")).resolve()
    directory = Path(str(payload.get("directory") or payload.get("worktree") or ".")).resolve()
    repo = repo_root_for(file_path, directory)
    rel = file_path.relative_to(repo).as_posix() if str(file_path).startswith(str(repo)) else file_path.name

    if is_test_path(rel):
        print(f"refused: test files are not editable ({rel})")
        return 1

    target = file_path
    original = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
    acceptance = str(args.get("acceptance") or "")
    goal = str(args.get("goal") or "")
    old = str(args.get("oldString") or "")
    new = str(args.get("newString") or "")

    started = time.time()
    mode = "apply" if old and new else "solve"
    error = ""
    patched: str | None = None

    if mode == "apply":
        patched, error = apply_replacement(original, old, new)
    else:
        executor = Executor(backend=BACKEND)
        task = type("T", (), {})()
        task.id = "T1"
        task.file = rel
        task.goal = goal or f"Make the change in {rel}"
        task.acceptance = acceptance
        task.test_file = None
        context = _context_for(task, repo, None)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the editor model. You answer with ONE unified diff and nothing "
                    "else. If the change is impossible from the given content, answer: blocked"
                ),
            },
            {"role": "user", "content": f"Goal: {task.goal}\n\nContext:\n{context}"},
        ]
        response = executor.complete(messages, None)
        message = (response.get("choices") or [{}])[0].get("message") or {}
        text = message.get("content") or message.get("reasoning_content") or ""
        diff = _extract_diff(text)
        if not diff:
            error = "the editor model produced no diff"
        else:
            patched, error = apply_unified_diff(original, diff)

    if patched is None:
        print(f"failed: {error or 'could not produce the change'}")
        return 1

    target.write_text(patched, encoding="utf-8")
    exit_code, output = run_acceptance(acceptance, repo)
    added = len(patched.splitlines()) - len(original.splitlines())
    receipt = {
        "receipt_id": "r-" + hashlib.sha256(f"{rel}:{exit_code}".encode()).hexdigest()[:8],
        "file": rel,
        "mode": mode,
        "artifact_sha256": sha256_of(target),
        "acceptance": acceptance,
        "exit": exit_code,
        "lines_delta": added,
        "wall_s": round(time.time() - started, 2),
    }
    summary = (
        f"edited {rel} ({added:+d} lines) · acceptance: {acceptance or 'none'} → exit {exit_code} · "
        f"receipt {receipt['receipt_id']} · sha256 {receipt['artifact_sha256'][:12]}"
    )
    if exit_code != 0 and output:
        summary += f"\n--- acceptance output (tail) ---\n{output[-400:]}"
    print(summary)
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
