"""Run the frozen metamorphic triples (name / ru / en) through investigate.

Reads frozen/TASKS.md (the table is the contract), runs 12 asks, prints per
formulation and per base task. Read-only.

Run: python experiments/xerj_2026_11/metamorphic/run_probe.py
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

ROW_RE = re.compile(r"^(\d+)\. (.+?):(\d+) ", re.M)
TASKS_FILE = HERE / "frozen" / "TASKS.md"


def parse() -> list[dict]:
    rows = []
    for line in TASKS_FILE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| T") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        base, name, ru, en, gold = cells[:5]
        gold = gold.strip("`")
        for form, question in (("name", name), ("ru", ru), ("en", en)):
            question = question.strip("`")
            rows.append({"base": base, "form": form, "question": question,
                         "gold": gold})
    if not rows:
        raise SystemExit("no tasks parsed from frozen/TASKS.md")
    return rows


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--hints", action="store_true",
                        help="pass the name form's identifiers as hints")
    args = parser.parse_args()

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

    tasks = parse()
    hint_for = {}
    if args.hints:
        from src.mcp.tools.investigate_tool import _identifiers

        for task in tasks:
            if task["form"] == "name":
                hint_for[task["base"]] = _identifiers(task["question"])
        print(f"hints: {hint_for}")

    results = []
    for task in tasks:
        hints = hint_for.get(task["base"]) if args.hints else None
        text = asyncio.run(
            tool.execute(query=task["question"], limit=8, hints=hints)
        )
        files = [f.replace("\\", "/") for _, f, _ in ROW_RE.findall(text)]
        top1 = bool(files) and files[0].endswith(task["gold"])
        any8 = any(f.endswith(task["gold"]) for f in files)
        verdict = re.search(r"verdict: (\w+)", text)
        row = {**task, "files": files[:3], "top1": top1, "any": any8,
               "verdict": verdict.group(1) if verdict else ""}
        results.append(row)
        print(f"  {task['base']:<3} {task['form']:<4} top1={top1} any={any8} "
              f"{row['verdict'] or '-':<9} {task['question'][:60]}")

    print("\nper form")
    for form in ("name", "ru", "en"):
        subset = [r for r in results if r["form"] == form]
        print(f"  {form:<4} top1={sum(r['top1'] for r in subset)}/{len(subset)} "
              f"any={sum(r['any'] for r in subset)}/{len(subset)}")

    print("\nper base")
    for base in sorted({r["base"] for r in results}):
        cells = {r["form"]: r for r in results if r["base"] == base}
        print(f"  {base}: " + "  ".join(
            f"{form}={'Y' if cells[form]['top1'] else 'n'}" for form in cells
        ))

    import json

    out = HERE / (
        "metamorphic_hints_results.json" if args.hints
        else "metamorphic_results.json"
    )
    out.write_text(
        json.dumps(results, ensure_ascii=False, indent=1),
        encoding="utf-8", newline="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
