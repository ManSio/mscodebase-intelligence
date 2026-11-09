"""Held-out panel: the gate on the E2 external corpora (design-blind).

The 15 tasks in `frozen/gold_external*.json` were written on 2026-11-08 for the
search-channel experiment, before the evidence gate existed. They are a
different corpus (two pinned external repos) and were not used to tune the
gate, so they are the closest thing to a held-out set this change has.

Same interleaved design as run_gate.py; the arms differ only in the env flag.

Run: python experiments/xerj_2026_11/evidence_gate/probe_heldout.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

GOLD_FILES = [EXP / "frozen" / "gold_external.json", EXP / "frozen" / "gold_external_v2.json"]
ROW_RE = re.compile(r"^(\d+)\. (.+?):(\d+)", re.M)
VERDICT_RE = re.compile(r"verdict: (\w+)(?: \(([0-9.]+)\))?")


def tasks() -> list[dict]:
    """Both frozen sets, v2 supersedes v1 for the same task id.

    v2 re-froze three tasks with a corrected gold rule; counting both would
    weight those three twice (review 2026-11-10).
    """
    by_id: dict[tuple[str, str], dict] = {}
    for gold_file in GOLD_FILES:  # v1 first, v2 overrides
        gold = json.loads(gold_file.read_text(encoding="utf-8"))
        for repo in gold["repos"]:
            project = Path(repo["path"])
            for task in repo["tasks"]:
                key = (repo["slug"], str(task["id"]))
                by_id[key] = {
                    "id": f"{repo['slug'][:6]}-{task['id']}",
                    "kind": task["kind"],
                    "question": task["question"],
                    "gold": task["gold"],
                    "root": project,
                    "slug": repo["slug"],
                }
    return list(by_id.values())


def _hit(files: list[str], gold: list[str]) -> bool:
    return any(any(g.endswith(f) for f in files) for g in gold)


def run_arm(arm: str, items: list[dict]) -> list[dict]:
    from src.core.di_container import (
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )
    from src.mcp.tools.investigate_tool import InvestigateTool

    services = create_service_collection(ROOT)
    registry = services.resolve(ProjectIndexerRegistry)
    factory = services.resolve(IndexerFactoryKey)
    tools = {}
    for project in {item["root"] for item in items}:
        if not (project / ".mscodebase" / "chunks.db").exists():
            raise SystemExit(f"{project} is not indexed; run fetch_external.py first")
        registry.get_indexer(project, factory=factory)
        tools[str(project)] = InvestigateTool(services)

    os.environ["MSCODEBASE_EVIDENCE_GATE"] = "0" if arm == "control" else "1"
    rows = []
    for item in items:
        text = asyncio.run(
            tools[str(item["root"])].execute(
                query=item["question"], limit=8, project_root=str(item["root"])
            )
        )
        files = [path.replace("\\", "/").split(f"{item['slug']}/")[-1]
                 for _, path, _ in ROW_RE.findall(text)]
        verdict = VERDICT_RE.search(text)
        rows.append({
            "arm": arm,
            "id": item["id"],
            "kind": item["kind"],
            "question": item["question"],
            "gold": item["gold"],
            "files": files,
            "top1": _hit(files[:1], item["gold"]),
            "any": _hit(files[:8], item["gold"]),
            "verdict": verdict.group(1) if verdict else "",
            "text": text,
        })
        print(f"  {arm:<9} {item['id']:<16} top1={rows[-1]['top1']} "
              f"any={rows[-1]['any']} {rows[-1]['verdict'] or '-':<9} "
              f"{item['question'][:54]}")
    return rows


def main() -> int:
    items = tasks()
    print(f"held-out tasks: {len(items)} "
          f"(repos: {sorted({item['slug'] for item in items})})")
    results = {"control": [], "treatment": []}
    for position, item in enumerate(items):
        order = (
            ["control", "treatment"] if position % 2 == 0
            else ["treatment", "control"]
        )
        for arm in order:
            results[arm].extend(run_arm(arm, [item]))

    (HERE / "heldout.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1),
        encoding="utf-8", newline="",
    )
    print("\nheld-out summary")
    for arm, rows in results.items():
        print(f"  {arm:<9} n={len(rows)} "
              f"top1={sum(r['top1'] for r in rows)/len(rows):.3f} "
              f"any={sum(r['any'] for r in rows)/len(rows):.3f} "
              f"verdicts={ {k: sum(r['verdict'] == k for r in rows) for k in ('answer', 'caveat', 'abstain', '')} }")
    changed = [
        r for r in results["treatment"]
        if (r["top1"], r["any"]) != next(
            (c["top1"], c["any"]) for c in results["control"] if c["id"] == r["id"]
        )
    ]
    print("\nchanged tasks:")
    for row in changed:
        control = next(c for c in results["control"] if c["id"] == row["id"])
        print(f"  {row['id']:<16} top1 {control['top1']}->{row['top1']} "
              f"any {control['any']}->{row['any']} verdict={row['verdict'] or '-'}")
    if not changed:
        print("  (none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
