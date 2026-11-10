"""Where do the repeated files sit in the answer?

E72 asked whether rank-5 localization loses to grep because a file can fill
several of the 8 slots. If the repeats sit at ranks 6-8, reordering cannot move
hit@5 - which is what the sqlalchemy run showed (11/40 either way).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey,
    ProjectIndexerRegistry,
    create_service_collection,
)
from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: E402

ROW_RE = re.compile(r"^\d+\. (.+?):(\d+) ", re.M)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    return out.stdout if out.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--tasks", type=int, default=20)
    args = parser.parse_args()

    corpus = Path(args.corpus)
    raw = _git(Path(args.repo), "log", f"{args.base}..HEAD", "--no-merges",
               "--format=%H%x00%B%x00").split("\x00")
    pairs = [(raw[i].strip(), raw[i + 1].strip()) for i in range(0, len(raw) - 1, 2)]
    tasks = [{"id": s[:12], "question": m} for s, m in pairs if s][: args.tasks]

    services = create_service_collection(corpus)
    services.resolve(ProjectIndexerRegistry).get_indexer(
        corpus, factory=services.resolve(IndexerFactoryKey)
    )
    tool = InvestigateTool(services)

    positions: Counter = Counter()
    duplicates = 0
    rows_total = 0
    for task in tasks:
        text = asyncio.run(tool.execute(query=task["question"], limit=8,
                                        project_root=str(corpus)))
        files = [f for f, _ in ROW_RE.findall(text)]
        seen: set = set()
        for index, file in enumerate(files, 1):
            rows_total += 1
            if file in seen:
                duplicates += 1
                positions[index] += 1
            else:
                seen.add(file)
        print(f"  {task['id']} rows={len(files)} distinct={len(set(files))}", flush=True)

    print(f"\nrows={rows_total} duplicate_rows={duplicates} "
          f"({duplicates / max(rows_total, 1):.2f} of rows)")
    print("duplicate row positions (1-based) in the answer:")
    for pos in sorted(positions):
        print(f"  rank {pos}: {positions[pos]}")
    ranked = sum(positions[p] for p in positions if p <= 5)
    print(f"duplicates at ranks 1-5: {ranked} of {duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
