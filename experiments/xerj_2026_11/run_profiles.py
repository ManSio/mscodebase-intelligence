"""Experiment: does the weight profile matter, and where?

Runs the same tasks under `def_first` and `exploratory` **in one process**
(the profile is read from the environment at call time), records top-10 and
rank-1 per task, and prints where the two answers differ.

Hypotheses are frozen in frozen/HYPOTHESES_PROFILES.md before this runs.

Run: python experiments/xerj_2026_11/run_profiles.py [--corpus ours|external|both]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from run_baseline import parse_tasks  # noqa: E402

OUT = HERE / "profiles.json"
PROFILES = ("def_first", "exploratory")


def _row_files(text: str, slug: str = "") -> list[str]:
    files = []
    for _r, path, _l in re.findall(r"^(\d+)\. (.+?):(\d+)", text, re.M):
        clean = path.replace("\\", "/")
        if slug and f"{slug}/" in clean:
            clean = clean.split(f"{slug}/")[-1]
        files.append(clean)
    return files


def _ok(kind: str, gold: list[str], files: list[str], top1: bool) -> bool:
    pool = files[:1] if top1 else files[:10]
    if kind == "negative":
        return not pool
    return any(any(g.endswith(f) for f in pool) for g in gold)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="both", choices=("ours", "external", "both"))
    args = parser.parse_args()

    from src.core.di_container import (  # noqa: E402
        IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
    )
    from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: E402

    services = create_service_collection(ROOT)
    registry = services.resolve(ProjectIndexerRegistry)
    factory = services.resolve(IndexerFactoryKey)
    tool = InvestigateTool(services)

    results: list[dict] = []
    try:
        corpora: list[dict] = []
        if args.corpus in ("ours", "both"):
            tasks = parse_tasks()
            corpora.append({"slug": "ours", "project": ROOT, "tasks": tasks})
        if args.corpus in ("external", "both"):
            gold = json.loads((HERE / "frozen" / "gold_external.json").read_text(encoding="utf-8"))
            gold2 = json.loads((HERE / "frozen" / "gold_external_v2.json").read_text(encoding="utf-8"))
            merged = {}
            for block in (gold, gold2):
                for repo in block["repos"]:
                    entry = merged.setdefault(repo["slug"], {"slug": repo["slug"],
                                                            "project": Path(repo["path"]),
                                                            "tasks": []})
                    known = {t["id"] for t in entry["tasks"]}
                    entry["tasks"] += [t for t in repo["tasks"] if t["id"] not in known]
            corpora += list(merged.values())

        for corpus in corpora:
            project = Path(corpus["project"])
            registry.get_indexer(project, factory=factory)
            for task in corpus["tasks"]:
                per_task = {"corpus": corpus["slug"], "id": task["id"], "kind": task["kind"],
                            "question": task["question"], "gold": task["gold"]}
                for profile in PROFILES:
                    os.environ["MSCODEBASE_INVESTIGATE_PROFILE"] = profile
                    text = asyncio.run(tool.execute(query=task["question"], limit=8,
                                                    project_root=str(project)))
                    files = _row_files(text, "" if corpus["slug"] == "ours" else corpus["slug"])
                    invalid = '"ok": false' in text[:300] or "Timeout after" in text
                    exact = re.search(r"exact: ([^\n]+)", text)
                    per_task[profile] = {
                        "files": files[:10],
                        "top10": None if invalid else _ok(task["kind"], task["gold"], files, False),
                        "top1": None if invalid else _ok(task["kind"], task["gold"], files, True),
                        "rows": len(files),
                        "exact": exact.group(1).strip() if exact else "",
                        "invalid": invalid,
                    }
                os.environ.pop("MSCODEBASE_INVESTIGATE_PROFILE", None)
                a, b = per_task["def_first"], per_task["exploratory"]
                per_task["differs"] = a["files"] != b["files"]
                per_task["has_identifier"] = bool(a["exact"])
                results.append(per_task)
                print(f"{per_task['corpus']:<9} {task['id']:<4} "
                      f"df top10={a['top10']} #1={a['top1']} | "
                      f"ex top10={b['top10']} #1={b['top1']} | differs={per_task['differs']}")
    finally:
        sd = getattr(services, "shutdown", None)
        if callable(sd):
            try:
                asyncio.run(sd())
            except Exception:
                pass

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8", newline="")

    print("\n=== summary")
    for profile in PROFILES:
        for scope in ("with_id", "no_id"):
            group = [r for r in results
                     if (r["has_identifier"] if scope == "with_id" else not r["has_identifier"])]
            group = [r for r in group if r[profile]["top10"] is not None]
            if not group:
                continue
            t10 = sum(bool(r[profile]["top10"]) for r in group) / len(group)
            t1 = sum(bool(r[profile]["top1"]) for r in group) / len(group)
            print(f"{profile:<12} {scope:<8} n={len(group):<3} top10={t10:.3f} rank1={t1:.3f}")
    diffs = [r["id"] for r in results if r["differs"]]
    no_id_diffs = [r["id"] for r in results if r["differs"] and not r["has_identifier"]]
    print(f"\ntasks whose answer changes between profiles: {len(diffs)} {diffs}")
    print(f"of them without an identifier: {len(no_id_diffs)} {no_id_diffs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
