"""Three-arm rewrite-gate experiment: on / off / smart.

Panel: XERJ 24 + the 3 mcp_audit RU questions (27 asks), one process, one
index, arms interleaved per task. Predictions were frozen in
frozen/REWRITE.md before the run.

Run: python experiments/xerj_2026_11/evidence_gate/probe_rewrite_arms.py
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
sys.path.insert(0, str(EXP))
sys.stdout.reconfigure(encoding="utf-8")

from run_baseline import parse_tasks, score  # noqa: E402

QUESTION_FILE = EXP / "mcp_audit" / "questions.json"
ROW_RE = re.compile(r"^(\d+)\. (.+?):(\d+) ", re.M)
VERDICT_RE = re.compile(r"verdict: (\w+)(?: \(([0-9.]+)\))?")
ARMS = ("on", "off", "smart")


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
    for root in {item["root"] for item in items}:
        registry.get_indexer(root, factory=factory)
        tools[str(root)] = InvestigateTool(services)
    return tools


def run_one(tool, item: dict, arm: str) -> dict:
    os.environ["MSCODEBASE_ASK_REWRITE"] = arm
    text = asyncio.run(
        tool.execute(query=item["question"], limit=8, project_root=str(item["root"]))
    )
    base = str(item["root"]).replace("\\", "/")
    files = [f.replace(base, "").lstrip("/") for _, f, _ in ROW_RE.findall(text)]
    verdict = VERDICT_RE.search(text)
    return {
        "arm": arm,
        "id": item["id"],
        "kind": item["kind"],
        "question": item["question"],
        "gold": item["gold"],
        "files": files,
        "rows": len(files),
        "top1": score(item, files[:1]),
        "any": score(item, files[:8]),
        "gated": (verdict.group(1) == "ask_rewrite") if verdict else False,
        "verdict": verdict.group(1) if verdict else "",
        "text": text,
    }


def main() -> int:
    items = tasks()
    print(f"tasks: {len(items)}; arms: {ARMS}")
    tools = _tools(items)
    results: dict[str, list[dict]] = {arm: [] for arm in ARMS}
    for position, item in enumerate(items):
        order = ARMS[position % len(ARMS):] + ARMS[: position % len(ARMS)]
        for arm in order:
            row = run_one(tools[str(item["root"])], item, arm)
            results[arm].append(row)
            print(f"  {arm:<6} {item['id']:<5} rows={row['rows']} "
                  f"top1={row['top1']} any={row['any']} "
                  f"{row['verdict'] or '-':<11} {item['question'][:48]}")

    (HERE / "rewrite_arms.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1),
        encoding="utf-8", newline="",
    )

    print("\nsummary")
    for arm in ARMS:
        rows = results[arm]
        positives = [r for r in rows if r["kind"] != "negative"]
        negatives = [r for r in rows if r["kind"] == "negative"]
        ru = [r for r in rows if r["id"].startswith("MSCRU")]
        neg_rows = sum(r["rows"] for r in negatives)
        print(f"  {arm:<6} gated={sum(r['gated'] for r in rows)}/{len(rows)} "
              f"nonneg top1={sum(r['top1'] for r in positives)/len(positives):.3f} "
              f"any={sum(r['any'] for r in positives)/len(positives):.3f} "
              f"negative_rows={neg_rows} ru_any="
              f"{sum(r['any'] for r in ru)/len(ru):.3f}")

    print("\nper-task gate (on/off/smart) and hits (top1/any):")
    for task_id in [t["id"] for t in items]:
        cells = []
        for arm in ARMS:
            row = next(r for r in results[arm] if r["id"] == task_id)
            cells.append(
                f"{'G' if row['gated'] else '-'}"
                f"{'1' if row['top1'] else '0'}"
                f"{'1' if row['any'] else '0'}"
            )
        print(f"  {task_id:<7} {' '.join(cells)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
