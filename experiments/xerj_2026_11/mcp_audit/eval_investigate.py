"""Measure investigate gold@1/gold@5 and latency on frozen questions.

Control vs treatment is the same process, same index, one toggle:
`MSCODEBASE_AUDIT_PENALTY=0` disables the tests/docs/history rank penalty,
`1` (default) keeps the shipped ranking. This makes the comparison paired.

Run (one project per process, to avoid cross-project registry interference):
  python experiments/xerj_2026_11/mcp_audit/eval_investigate.py \
      --project mscodebase --penalty 0
  ... --penalty 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8")

import re  # noqa: E402

ROW_RE = re.compile(r"^\d+\. ([^:\n]+):(\d+)", re.MULTILINE)


def load_questions() -> dict:
    return json.loads((HERE / "questions.json").read_text(encoding="utf-8"))


def build_tool(root: str):
    from src.core.di_container import (
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )
    from src.core.indexing.project_indexer_registry import ProjectState
    from src.mcp.tools.investigate_tool import InvestigateTool

    services = create_service_collection(Path(root))
    registry = services.resolve(ProjectIndexerRegistry)
    registry.get_indexer(root, factory=services.resolve(IndexerFactoryKey))
    registry.set_state(Path(root), ProjectState.READY)
    return InvestigateTool(services)


def files_of(text: str) -> list[str]:
    return [m.group(1).strip() for m in ROW_RE.finditer(text or "")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--penalty", choices=["0", "1"], default="1")
    ap.add_argument("--names", choices=["0", "1"], default="1")
    ap.add_argument("--parallel", action="store_true")
    args = ap.parse_args()

    data = load_questions()["projects"][args.project]
    root = data["root"]

    if args.penalty == "0":
        import src.mcp.tools.investigate_tool as inv

        inv._bucket_penalty = lambda *a, **k: 0.0
    if args.names == "0":
        import src.mcp.tools.investigate_tool as inv

        inv._name_variants = lambda *a, **k: []

    tool = build_tool(root)
    rows = []
    for question, gold in data["questions"]:
        started = time.perf_counter()
        text = asyncio.run(
            tool.execute(question, limit=5, project_root=root, rerank=False)
        )
        elapsed = time.perf_counter() - started
        files = files_of(text)
        rank = next((i + 1 for i, f in enumerate(files) if gold in f), None)
        rows.append(
            {
                "q": question,
                "gold": gold,
                "rank": rank,
                "ms": round(elapsed * 1000),
                "files": files[:5],
            }
        )

    ru_rows = []
    for question, gold in data["ru"]:
        started = time.perf_counter()
        text = asyncio.run(
            tool.execute(question, limit=5, project_root=root, rerank=False)
        )
        elapsed = time.perf_counter() - started
        files = files_of(text)
        ru_rows.append(
            {
                "q": question,
                "gold": gold,
                "rank": next((i + 1 for i, f in enumerate(files) if gold in f), None),
                "ms": round(elapsed * 1000),
                "files": files[:5],
            }
        )

    parallel = None
    if args.parallel:
        qs = [q for q, _ in data["questions"]]
        started = time.perf_counter()

        async def run_all():
            return await asyncio.gather(
                *(tool.execute(q, limit=4, project_root=root, rerank=False) for q in qs),
                return_exceptions=True,
            )

        results = asyncio.run(run_all())
        parallel = {
            "wall_ms": round((time.perf_counter() - started) * 1000),
            "n": len(qs),
            "errors": sum(1 for r in results if isinstance(r, Exception)),
        }

    def summary(items):
        n = len(items)
        test_re = re.compile(
            r"(^|/)(tests?|__tests__|specs?)/|(^|/)test_[^/]+$|(^|/)conftest\.py$"
        )
        return {
            "n": n,
            "top1": sum(1 for r in items if r["rank"] == 1),
            "top5": sum(1 for r in items if r["rank"] and r["rank"] <= 5),
            "median_ms": sorted(r["ms"] for r in items)[n // 2] if n else 0,
            "max_ms": max((r["ms"] for r in items), default=0),
            # Root-level test_*.py counts too (httpbin keeps its tests at the
            # repo root; the old metric reported 0 slots for it).
            "test_or_doc_slots": sum(
                1
                for r in items
                for f in r["files"]
                if f.startswith("docs/") or test_re.search(f)
            ),
        }

    out = {
        "project": args.project,
        "root": root,
        "penalty": args.penalty,
        "summary": summary(rows),
        "ru_summary": summary(ru_rows) if ru_rows else None,
        "rows": rows,
        "ru_rows": ru_rows,
        "parallel": parallel,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
