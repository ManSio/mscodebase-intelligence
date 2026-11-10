"""P4 of E72: with the flag off, the answer text must not change at all.

Two source trees are compared on the same corpus, the same 10 commits and the
same flag state (off): `--src` pins the tree, `--out` receives the answers, and
`diff` decides. This compares text, not metrics.

    python experiments/file_dedup_2026_11/p4_identity.py --src D:\\Project\\bench-p4 \
        --corpus D:\\Project\\bench-ext\\sa-B --repo D:\\Project\\bench-ext\\sqlalchemy \
        --base 8b62343 --out C:\\...\\p4_baseline.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

ROW_RE = re.compile(r"^\d+\. (.+?):(\d+) ", re.M)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    return out.stdout if out.returncode == 0 else ""


def _tasks(repo: Path, base: str, limit: int) -> list[dict]:
    raw = _git(repo, "log", f"{base}..HEAD", "--no-merges",
               "--format=%H%x00%B%x00").split("\x00")
    pairs = [(raw[i].strip(), raw[i + 1].strip()) for i in range(0, len(raw) - 1, 2)]
    return [{"id": sha[:12], "sha": sha, "question": message}
            for sha, message in pairs if sha][:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--tasks", type=int, default=10)
    args = parser.parse_args()

    sys.path.insert(0, args.src)
    sys.stdout.reconfigure(encoding="utf-8")
    from src.core.di_container import (  # noqa: E402
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )
    from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: E402

    assert str(Path(args.src).resolve()) in str(
        Path(sys.modules["src"].__file__).resolve()), "src did not come from --src"

    corpus = Path(args.corpus)
    services = create_service_collection(corpus)
    services.resolve(ProjectIndexerRegistry).get_indexer(
        corpus, factory=services.resolve(IndexerFactoryKey)
    )
    tool = InvestigateTool(services)

    answers = {}
    for task in _tasks(Path(args.repo), args.base, args.tasks):
        answers[task["id"]] = asyncio.run(tool.execute(
            query=task["question"], limit=8, project_root=str(corpus)))
        print(f"  {task['id']} rows={len(ROW_RE.findall(answers[task['id']]))}",
              flush=True)

    Path(args.out).write_text(json.dumps(answers, ensure_ascii=False, indent=1),
                              encoding="utf-8", newline="")
    print(f"wrote {len(answers)} answers to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
