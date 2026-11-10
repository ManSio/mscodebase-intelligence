"""Two-arm probe: demote scripts/examples/benches/fuzz rows for code questions.

Control `MSCODEBASE_SCRIPTS_DEMOTE=0`, treatment `=1`, interleaved per task.
Panel: the 16 XERJ positive asks (gold file known). Read-only otherwise.

Run: python experiments/xerj_2026_11/probe_scripts_demote.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding="utf-8")

from run_baseline import parse_tasks, score  # noqa: E402

ROW_RE = re.compile(r"^(\d+)\. (.+?):(\d+) ", re.M)


def main() -> int:
    from src.core.di_container import (
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )
    from src.mcp.tools.investigate_tool import InvestigateTool

    services = create_service_collection(ROOT)
    services.resolve(ProjectIndexerRegistry).get_indexer(
        ROOT, factory=services.resolve(IndexerFactoryKey)
    )
    tool = InvestigateTool(services)

    tasks = parse_tasks()
    results = {"control": [], "treatment": []}
    for position, task in enumerate(tasks):
        order = (
            ["control", "treatment"] if position % 2 == 0
            else ["treatment", "control"]
        )
        for arm in order:
            os.environ["MSCODEBASE_SCRIPTS_DEMOTE"] = "0" if arm == "control" else "1"
            text = asyncio.run(tool.execute(query=task["question"], limit=8))
            files = [f.replace("\\", "/") for _, f, _ in ROW_RE.findall(text)]
            results[arm].append({
                "id": task["id"],
                "kind": task["kind"],
                "files": files,
                "top1": score(task, files[:1]),
                "any": score(task, files[:8]),
            })
            print(f"  {arm:<9} {task['id']:<4} top1={results[arm][-1]['top1']} "
                  f"any={results[arm][-1]['any']} first={files[:2]}")

    print("\nsummary")
    for arm, rows in results.items():
        for kind in ("positive", "ambiguity", "negative"):
            subset = [r for r in rows if r["kind"] == kind]
            print(f"  {arm:<9} {kind:<10} n={len(subset)} "
                  f"top1={sum(r['top1'] for r in subset)}/{len(subset)} "
                  f"any={sum(r['any'] for r in subset)}/{len(subset)}")
    print("\nchanged tasks:")
    for a, b in zip(results["control"], results["treatment"]):
        if (a["top1"], a["any"]) != (b["top1"], b["any"]):
            print(f"  {a['id']}: top1 {a['top1']}->{b['top1']} "
                  f"any {a['any']}->{b['any']}  first={b['files'][:2]}")
    (HERE / "scripts_demote_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1),
        encoding="utf-8", newline="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
