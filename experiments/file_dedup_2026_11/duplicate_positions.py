"""Where do the repeated files sit in the answer, ON THE TASK POPULATION?

E72's motivation used a raw `git log` sample, which includes docs-only commits
with no `.py` gold - a different population than the 40-task panel. This script
applies the same task filter as the benchmark and asserts that the population
matches, so the number cannot be quoted against the wrong denominator again.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "bench_2026_11"))
sys.stdout.reconfigure(encoding="utf-8")

import re  # noqa: E402

from external import _tasks  # noqa: E402
from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey,
    ProjectIndexerRegistry,
    create_service_collection,
)
from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: E402

ROW_RE = re.compile(r"^\d+\. (.+?):(\d+) ", re.M)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--tasks", type=int, default=40)
    args = parser.parse_args()

    corpus = Path(args.corpus)
    tasks = _tasks(Path(args.repo), args.base, args.tasks)
    if len(tasks) != args.tasks:
        print(f"population mismatch: asked {args.tasks}, benchmark rule kept "
              f"{len(tasks)} - refusing to report a share on a different denominator")
        return 2
    print(f"corpus={corpus.name} tasks={len(tasks)} (benchmark filter applied)")

    services = create_service_collection(corpus)
    services.resolve(ProjectIndexerRegistry).get_indexer(
        corpus, factory=services.resolve(IndexerFactoryKey))
    tool = InvestigateTool(services)

    positions: Counter = Counter()
    duplicates = 0
    rows_total = 0
    empty = 0
    for task in tasks:
        text = asyncio.run(tool.execute(query=task["question"], limit=8,
                                        project_root=str(corpus)))
        files = [f for f, _ in ROW_RE.findall(text)]
        if not files:
            empty += 1
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
          f"({duplicates / max(rows_total, 1):.2f} of rows) empty_answers={empty}")
    print("duplicate row positions (1-based):")
    for pos in sorted(positions):
        print(f"  rank {pos}: {positions[pos]}")
    print(f"duplicates at ranks 1-5: "
          f"{sum(positions[p] for p in positions if p <= 5)} of {duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
