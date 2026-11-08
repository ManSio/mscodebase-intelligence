"""Build the main-run corpus from real bugs in this repository's history.

Method (SWE-bench style, from our own history):

- a task = one commit that fixed a source file AND changed its test file;
- the snapshot is the **parent** of that commit (`src/` + `tests/` only, so the
  agent cannot read AGENT_DIARY.md / KNOWN_ISSUES.md and find the answer);
- the hidden test is the test file as of the fix commit;
- a task is admitted only if the test **fails** on the snapshot (negative
  control: the bug is really there) and **passes** after the real fix is
  applied (positive control: the task is solvable and the test is the right
  one).

The corpus is materialised at run time from the recorded SHAs, so the frozen
input stays small and reproducible.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1] / "frozen" / "corpus"
EXCLUDE_FROM_SNAPSHOT = ("experiments/", "docs/", "AGENT_DIARY.md", "KNOWN_ISSUES.md")


def git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd or REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr[-400:]}")
    return proc.stdout


@dataclass
class Candidate:
    sha: str
    subject: str
    src_files: list[str]
    test_files: list[str]


def candidates(limit: int = 700) -> list[Candidate]:
    raw = git("log", "--no-merges", "--pretty=format:%H|%s", f"-n{limit}", "--name-only")
    out: list[Candidate] = []
    sha = subject = None
    files: list[str] = []
    for line in raw.splitlines():
        if re.match(r"^[0-9a-f]{40}\|", line):
            if sha:
                out.append(Candidate(sha, subject, _pick(files, "src/"), _pick(files, "tests/")))
            sha, subject = line.split("|", 1)
            files = []
        elif line.strip() and sha:
            files.append(line.strip())
    if sha:
        out.append(Candidate(sha, subject, _pick(files, "src/"), _pick(files, "tests/")))
    return [c for c in out if c.src_files and c.test_files and len(c.src_files) <= 2 and len(c.test_files) <= 2]


def _pick(files: list[str], prefix: str) -> list[str]:
    return [f for f in files if f.startswith(prefix) and f.endswith(".py")][:2]


def materialize(sha: str, dest: Path) -> None:
    """Extract src/ and tests/ (plus pytest config) of a commit into dest."""
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for candidate in ("src", "tests", "pytest.ini", "pyproject.toml", "conftest.py"):
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}:{candidate}"],
            cwd=str(REPO),
            capture_output=True,
            timeout=60,
        ).returncode == 0
        if exists:
            paths.append(candidate)
    tar_bytes = subprocess.run(
        ["git", "archive", "--format=tar", sha, *paths],
        cwd=str(REPO),
        capture_output=True,
        timeout=300,
    )
    if tar_bytes.returncode != 0:
        raise RuntimeError(f"git archive {sha} failed: {tar_bytes.stderr[-300:]!r}")
    import io

    with tarfile.open(fileobj=io.BytesIO(tar_bytes.stdout)) as tar:
        members = [m for m in tar.getmembers() if not any(m.name.startswith(e) for e in EXCLUDE_FROM_SNAPSHOT)]
        tar.extractall(dest, members=members)


def apply_fix(sha: str, src_rel: str, dest: Path) -> None:
    content = subprocess.run(
        ["git", "show", f"{sha}:{src_rel}"],
        cwd=str(REPO),
        capture_output=True,
        timeout=120,
    ).stdout
    target = dest / src_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def run_test(snapshot: Path, test_rels: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *test_rels, "-q", "-p", "no:cacheprovider", "--no-header", "-x"],
        cwd=str(snapshot),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env={**dict(__import__("os").environ), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def failing_tests(snapshot: Path, test_rels: list[str]) -> list[str]:
    """Test ids that fail on the snapshot (pytest --collect-only + run)."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *test_rels,
            "-q",
            "-p",
            "no:cacheprovider",
            "--no-header",
            "-rf",
        ],
        cwd=str(snapshot),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    ids = re.findall(r"FAILED\s+(\S+)", proc.stdout or "")
    return sorted(set(ids))


def is_rename_shaped(parent: str, fix: str, src_rel: str) -> bool:
    """True if the fix is (or contains) a rename of a public function.

    A rename-shaped task is unusable: the parent's code state is not the state
    the fix was written against, so the "expected" direction is unknowable from
    inside the snapshot. The first corpus task we built was exactly that — the
    agent produced a plausible rename and still failed the hidden set.
    """
    diff = git("diff", parent, fix, "--", src_rel)
    removed = set(re.findall(r"^-\s*def\s+(\w+)", diff, re.M))
    added = set(re.findall(r"^\+\s*def\s+(\w+)", diff, re.M))
    return bool(removed & added)


def build_one(cand: Candidate) -> dict | None:
    parent = git("rev-parse", f"{cand.sha}^").strip()
    src_rel, test_rel = cand.src_files[0], cand.test_files[0]
    if any(is_rename_shaped(parent, cand.sha, s) for s in cand.src_files):
        return None
    with tempfile.TemporaryDirectory(prefix="corpus-") as tmp:
        snapshot = Path(tmp) / "snap"
        materialize(parent, snapshot)
        if not (snapshot / src_rel).is_file():
            return None
        # the test files as of the FIX commit (they may be new or changed there)
        for rel in cand.test_files:
            blob = subprocess.run(
                ["git", "show", f"{cand.sha}:{rel}"],
                cwd=str(REPO),
                capture_output=True,
                timeout=120,
            ).stdout
            if blob:
                (snapshot / rel).parent.mkdir(parents=True, exist_ok=True)
                (snapshot / rel).write_bytes(blob)

        before_rc, before_out = run_test(snapshot, cand.test_files)
        if before_rc == 0:
            return None  # the test already passes: no bug to find
        fail_ids = failing_tests(snapshot, cand.test_files)
        if not fail_ids:
            return None  # collection error rather than a behavioural failure

        for rel in cand.src_files:
            apply_fix(cand.sha, rel, snapshot)
        after_rc, after_out = run_test(snapshot, cand.test_files)
        if after_rc != 0:
            return None  # the real fix does not make it pass: unusable task

        return {
            "task_id": f"{cand.sha[:10]}_{Path(src_rel).stem}",
            "source": "own-repo-history",
            "parent_sha": parent,
            "fix_sha": cand.sha,
            "subject": cand.subject,
            "src_file": src_rel,
            "src_files": cand.src_files,
            "test_file": test_rel,
            "test_files": cand.test_files,
            "fail_to_pass": fail_ids,
            "class": "fix",
            "snapshot_paths": ["src", "tests", "pytest.ini", "pyproject.toml"],
            "excluded_from_snapshot": list(EXCLUDE_FROM_SNAPSHOT),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=12)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    built: list[dict] = []
    for cand in candidates():
        if len(built) >= args.max:
            break
        try:
            task = build_one(cand)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {cand.sha[:10]}: {type(exc).__name__}: {exc}")
            continue
        if task is None:
            continue
        path = out_dir / f"{task['task_id']}.json"
        path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        built.append(task)
        print(f"  OK {task['task_id']}  {task['subject'][:70]}")
        print(f"     {task['src_file']}  ->  {task['test_file']}  fail_to_pass={len(task['fail_to_pass'])}")

    index = out_dir / "index.json"
    index.write_text(
        json.dumps(
            {"n_tasks": len(built), "tasks": [t["task_id"] for t in built]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nbuilt {len(built)} tasks -> {out_dir}")
    return 0 if built else 2


if __name__ == "__main__":
    raise SystemExit(main())

