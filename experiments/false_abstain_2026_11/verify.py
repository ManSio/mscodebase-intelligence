"""E73 verification: negatives must stay silent, the 13 abstains must answer.

P3 — 44 negative tasks from the scale panel (`where is zz_<hex> defined`) must
produce no rows. P4 — the 13 commits that used to answer nothing must put the
gold file in the top-5.

    python experiments/false_abstain_2026_11/verify.py \
        --corpus D:\\Project\\bench-ext\\sa-B --repo D:\\Project\\bench-ext\\sqlalchemy \
        --base 8b62343 --panel D:\\Project\\MSCodeBase\\experiments\\scale_2026_11\\tasks.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "bench_2026_11"))
sys.stdout.reconfigure(encoding="utf-8")

from external import _files, _norm, _tasks  # noqa: E402
from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey,
    ProjectIndexerRegistry,
    create_service_collection,
)
from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: E402

ROW_RE = re.compile(r"^\d+\. (.+?):(\d+) ", re.M)
EMPTY_IDS = ["65ea6bee8214", "749086adb0cc", "d211100c20f1", "f1693787ade6",
             "f679f8bb1a3e", "98ad157d6334", "049ed1db162a", "975ffa7d77ee",
             "ad395ad4998d", "f1029a165da6", "6165193fb3f4", "956a0235027e",
             "ffed1d70148e"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    corpus = Path(args.corpus)
    services = create_service_collection(corpus)
    services.resolve(ProjectIndexerRegistry).get_indexer(
        corpus, factory=services.resolve(IndexerFactoryKey))
    tool = InvestigateTool(services)

    negatives = [json.loads(line) for line in Path(args.panel).read_text(
        encoding="utf-8").splitlines() if line.strip()]
    negatives = [t for t in negatives if t.get("kind") == "negative"]
    leaked = []
    for task in negatives:
        text = asyncio.run(tool.execute(query=task["question"], limit=args.limit,
                                        project_root=str(corpus)))
        rows = len(ROW_RE.findall(text))
        if rows:
            leaked.append((task["id"], rows))
    print(f"P3 negatives: {len(negatives) - len(leaked)}/{len(negatives)} silent, "
          f"leaks={leaked}")

    tasks = {t["id"]: t for t in _tasks(Path(args.repo), args.base, 40)}
    missing = [i for i in EMPTY_IDS if i not in tasks]
    if missing:
        print(f"population mismatch: {missing} are not in the 40-task list")
        return 2
    recovered = 0
    for short in EMPTY_IDS:
        task = tasks[short]
        text = asyncio.run(tool.execute(query=task["question"], limit=args.limit,
                                        project_root=str(corpus)))
        files = _norm(_files(text), corpus)
        hit5 = any(any(g in f for f in files[:5]) for g in task["gold"])
        recovered += hit5
        print(f"  {short} rows={len(files)} hit@5={hit5}")
    print(f"P4 formerly-empty recovered: {recovered}/{len(EMPTY_IDS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
