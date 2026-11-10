"""Build commit-localization tasks from git history, by one fixed rule.

Frozen spec: `frozen/PLAN.md`. The query is a commit message we did not write;
the gold is what git says the commit changed. Nothing here inspects the tool.

Run:
    python experiments/bench_2026_11/commit_tasks.py
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

BASE = "7c2c7a3c6417539bc08f807d6790fe6e722d3a84"  # session B, frozen in PLAN.md
CODE_DIRS = ("src/", "tests/", "scripts/", "tools/")
NEVER_GOLD = re.compile(
    r"^(CHANGELOG\.md|.*\.lock|requirements.*\.txt|pyproject\.toml|experiments/)",
    re.I,
)
MAX_FILES = 20
MIN_MESSAGE = 20
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr[:200]}")
    return out.stdout


def _commits() -> list[tuple[str, str, str]]:
    """(sha, date, message) for non-merge commits in (BASE, HEAD]."""
    raw = _git("log", f"{BASE}..HEAD", "--no-merges",
               "--format=%H%x00%ad%x00%B%x00", "--date=short")
    parts = raw.split("\x00")
    out = []
    for sha, date, message in zip(parts[0::3], parts[1::3], parts[2::3]):
        sha, date = sha.strip(), date.strip()
        if sha and date:
            out.append((sha, date, message.strip()))
    return out


def _files(sha: str) -> list[str]:
    return [line.strip() for line in
            _git("show", "--name-only", "--format=", sha).splitlines() if line.strip()]


def main() -> int:
    tasks = []
    for sha, date, message in _commits():
        files = _files(sha)
        if not files or len(files) > MAX_FILES:
            continue
        if len(message) < MIN_MESSAGE:
            continue
        if not any(f.startswith(CODE_DIRS) for f in files):
            continue
        gold = sorted(f for f in files
                      if f.startswith(CODE_DIRS) and not NEVER_GOLD.match(f))
        if not gold:
            continue
        tasks.append({
            "id": sha[:12],
            "sha": sha,
            "date": date,
            # The third-party data gate blocks personal emails (a commit message
            # quoted a contributor address). Redaction is part of the rule, not a
            # post-hoc edit: it is applied before the manifest is hashed.
            "question": EMAIL_RE.sub("<email>", message),
            "gold": gold,
        })

    tasks.sort(key=lambda t: (t["date"], t["id"]))
    cut = int(len(tasks) * 0.7)
    for index, task in enumerate(tasks):
        task["split"] = "dev" if index < cut else "sealed"

    out = HERE / "tasks.jsonl"
    out.write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in tasks) + "\n",
                   encoding="utf-8", newline="")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (HERE / "MANIFEST.sha256").write_text(
        f"{digest}  tasks.jsonl\nbase={BASE}\n", encoding="utf-8", newline="")

    print(f"base={BASE[:12]} tasks={len(tasks)} dev={cut} sealed={len(tasks) - cut}")
    print(f"sha256={digest}")
    for split in ("dev", "sealed"):
        subset = [t for t in tasks if t["split"] == split]
        files = [len(t["gold"]) for t in subset]
        print(f"  {split:<6} n={len(subset):<3} "
              f"gold_files mean={sum(files) / max(len(files), 1):.1f} "
              f"max={max(files) if files else 0} "
              f"dates={subset[0]['date'] if subset else '-'}..{subset[-1]['date'] if subset else '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
