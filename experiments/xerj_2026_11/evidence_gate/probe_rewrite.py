"""What does the ask-for-identifier gate cost, and what does it buy?

XERJ N03 is the case it was built for: the words exist, the subject does not,
and neighbours look like an answer. It also fires on real Russian questions
that name no identifier - all three `mcp_audit` RU questions.

This probe measures both, interleaved, with the evidence gate always on:

  rewrite ON   MSCODEBASE_ASK_REWRITE=1
  rewrite OFF  MSCODEBASE_ASK_REWRITE=0  (rows returned with a verdict)

Run: python experiments/xerj_2026_11/evidence_gate/probe_rewrite.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EXP))
sys.stdout.reconfigure(encoding="utf-8")

from run_baseline import parse_tasks, score  # noqa: E402

QUESTION_FILE = EXP / "mcp_audit" / "questions.json"
ROW_RE = re.compile(r"^(\d+)\. (.+?):(\d+) ", re.M)
VERDICT_RE = re.compile(r"verdict: (\w+)(?: \(([0-9.]+)\))?")


def tasks() -> list[dict]:
    result = []
    for task in parse_tasks():
        result.append({**task, "panel": "xerj", "root": ROOT})
    data = json.loads(QUESTION_FILE.read_text(encoding="utf-8"))
    for project, spec in data["projects"].items():
        for index, (question, gold) in enumerate(spec.get("ru") or [], 1):
            result.append({
                "id": f"{project[:3].upper()}RU{index}",
                "kind": "positive",
                "question": question,
                "gold": [gold],
                "tokens": [],
                "panel": "mcp_audit",
                "root": Path(spec["root"]),
            })
    return result


def _tools(items: list[dict]):
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
    for root in {str(item["root"]) for item in items}:
        registry.get_indexer(root, factory=factory)
        tools[root] = InvestigateTool(services)
    return tools


def run_one(tool, item: dict, arm: str) -> dict:
    from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: F401

    os.environ["MSCODEBASE_ASK_REWRITE"] = "1" if arm == "rewrite_on" else "0"
    text = asyncio.run(
        tool.execute(query=item["question"], limit=8, project_root=str(item["root"]))
    )
    base = str(item["root"]).replace("\\", "/")
    files = [f.replace(base, "").lstrip("/") for _, f, _ in ROW_RE.findall(text)]
    verdict = VERDICT_RE.search(text)
    row = {
        "arm": arm,
        "id": item["id"],
        "kind": item["kind"],
        "question": item["question"],
        "files": files,
        "top1": score(item, files[:1]),
        "any": score(item, files[:8]),
        "rows": len(files),
        "verdict": verdict.group(1) if verdict else "",
        "text": text,
    }
    print(f"  {arm:<11} {item['id']:<5} rows={len(files)} "
          f"top1={row['top1']} any={row['any']} "
          f"{row['verdict'] or '-':<11} {item['question'][:52]}")
    return row


def main() -> int:
    items = tasks()
    cleanup = EXP / "mcp_audit" / "questions.json"
    answer = json.loads(cleanup.read_text(encoding="utf-8"))
    ru_count = sum(len(spec.get("ru") or []) for spec in answer["projects"].values())
    print(f"tasks: {len(items)} (xerj {len(items) - ru_count}, ru {ru_count})")

    tools = _tools(items)
    results = {"rewrite_on": [], "rewrite_off": []}
    for position, item in enumerate(items):
        order = (
            ["rewrite_on", "rewrite_off"] if position % 2 == 0
            else ["rewrite_off", "rewrite_on"]
        )
        for arm in order:
            results[arm].append(run_one(tools[str(item["root"])], item, arm))

    (HERE / "rewrite_tradeoff.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1),
        encoding="utf-8", newline="",
    )

    print("\nsummary")
    for arm, rows in results.items():
        negatives = [r for r in rows if r["kind"] == "negative"]
        positives = [r for r in rows if r["kind"] != "negative"]
        ru = [r for r in rows if r["id"].startswith("MSCRU")]
        print(f"  {arm:<11} positive top1={sum(r['top1'] for r in positives)/len(positives):.3f} "
              f"any={sum(r['any'] for r in positives)/len(positives):.3f} "
              f"negative_rows={statistics.mean(r['rows'] for r in negatives):.2f} "
              f"ru any={sum(r['any'] for r in ru)/len(ru):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
