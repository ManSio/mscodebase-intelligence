"""Build a bounded Brief for one microtask.

The worker never explores the repository. This module decides exactly which
files it may see, and refuses to emit an oversized Brief instead of silently
truncating the task.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_BRIEF_BYTES = 8000
MAX_FILE_READS = 3
MAX_FILE_CHARS = 3000
ACCEPTANCE_TEST_RE = re.compile(r"(tests/[\w./-]+\.py)")

RULES = """\
## Rules
- Edit only the allowed files listed above.
- Do not edit tests.
- Run the acceptance command exactly as written.
- Do not search the repository, do not spawn agents, do not use MCP.
- If the Brief is insufficient, return status "blocked" instead of guessing.
"""


class BriefTooLarge(RuntimeError):
    pass


@dataclass
class Brief:
    task_id: str
    text: str
    files_read: list[str] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.text.encode("utf-8"))

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "bytes": self.size,
            "files_read": self.files_read,
            "truncated": self.truncated,
        }


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n# [TRUNCATED BY BRIEF BUILDER]\n", True


def _acceptance_tests(acceptance: str) -> list[str]:
    found: list[str] = []
    for match in ACCEPTANCE_TEST_RE.findall(acceptance):
        clean = match.split("::")[0]
        if clean not in found:
            found.append(clean)
    return found


def build_brief(task: dict, repo_root: Path) -> Brief:
    task_id = task["id"]
    allowed = [str(f).replace("\\", "/") for f in task["files"]]

    candidates: list[str] = []
    for rel in allowed:
        if rel not in candidates:
            candidates.append(rel)
    for rel in _acceptance_tests(task.get("acceptance", "")):
        if rel not in candidates:
            candidates.append(rel)

    if len(candidates) > MAX_FILE_READS:
        raise BriefTooLarge(
            f"{task_id}: {len(candidates)} files needed, limit is {MAX_FILE_READS}"
        )

    header = (
        f"# Brief {task_id}\n\n"
        f"## Goal\n\n{task['goal']}\n\n"
        f"## Symbol\n\n`{task['symbol']}`\n\n"
        f"## Allowed files\n\n" + "\n".join(f"- `{rel}`" for rel in allowed) + "\n\n"
        f"## Acceptance\n\n```text\n{task['acceptance']}\n```\n\n"
        f"## Context\n\n"
    )
    if len((header + RULES).encode("utf-8")) > MAX_BRIEF_BYTES:
        raise BriefTooLarge(f"{task_id}: the brief header alone exceeds {MAX_BRIEF_BYTES} bytes")

    files_read: list[str] = []
    truncated: list[str] = []
    # The cap is a design target, not a kill switch: a valid task with a big
    # module must still get a worker, so the context is clipped until it fits.
    per_file = MAX_FILE_CHARS
    while True:
        context: list[str] = []
        files_read = []
        truncated = []
        for rel in candidates:
            path = repo_root / rel
            if not path.is_file():
                # A referenced file that does not exist is a fact, not a crash:
                # the block class is exactly "the specification is missing".
                files_read.append(rel)
                truncated.append(rel)
                context.append(f"### `{rel}`\n\n**not present in this repository**\n")
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            body, was_cut = _clip(raw, per_file)
            if was_cut:
                truncated.append(rel)
            files_read.append(rel)
            context.append(f"### `{rel}`\n\n```python\n{body}```\n")
        text = header + "\n".join(context) + "\n" + RULES
        if len(text.encode("utf-8")) <= MAX_BRIEF_BYTES:
            return Brief(task_id=task_id, text=text, files_read=files_read, truncated=truncated)
        if per_file <= 400:
            raise BriefTooLarge(
                f"{task_id}: brief is {len(text.encode('utf-8'))} bytes and the context "
                f"cannot be clipped further (limit {MAX_BRIEF_BYTES})"
            )
        per_file = max(400, per_file // 2)


def selftest() -> int:
    repo = Path(__file__).resolve().parents[1] / "frozen" / "repo"
    plan_path = Path(__file__).resolve().parents[1] / "frozen" / "plans" / "P2_money.json"
    if not plan_path.is_file():
        print("SELFTEST FAIL: frozen reference plan is missing")
        return 1
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    briefs = [build_brief(task, repo) for task in plan["tasks"]]
    for brief in briefs:
        if brief.size > MAX_BRIEF_BYTES:
            print(f"SELFTEST FAIL: {brief.task_id} is {brief.size} bytes")
            return 1
        if len(brief.files_read) > MAX_FILE_READS:
            print(f"SELFTEST FAIL: {brief.task_id} reads {len(brief.files_read)} files")
            return 1
        if "tests/test_public.py" in brief.files_read and "hidden" in brief.text:
            print(f"SELFTEST FAIL: {brief.task_id} leaks hidden tests")
            return 1

    oversized = {
        "id": "T1",
        "goal": "x",
        "symbol": "tinycalc.core.mean",
        "files": ["tinycalc/core.py"],
        "depends_on": [],
        "acceptance": "python -m pytest tests/test_public.py -q",
        "max_steps": 3,
    }
    brief = build_brief(oversized, repo)
    if "hidden" in brief.text:
        print("SELFTEST FAIL: hidden path leaked into brief")
        return 1

    print(
        "SELFTEST: PASS ("
        + ", ".join(f"{b.task_id}={b.size}B/{len(b.files_read)}files" for b in briefs)
        + ")"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", nargs="?")
    parser.add_argument("--repo")
    parser.add_argument("--task")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.plan:
        parser.error("plan path or --selftest is required")

    experiment = Path(__file__).resolve().parents[1]
    repo = Path(args.repo) if args.repo else experiment / "frozen" / "repo"
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    for task in plan.get("tasks", []):
        if args.task and task["id"] != args.task:
            continue
        brief = build_brief(task, repo)
        print(brief.text)
        print("---")
        print(json.dumps(brief.as_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

