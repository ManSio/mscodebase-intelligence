"""Run the commit-localization benchmark (frozen: `frozen/PLAN.md`).

Corpus is a worktree at the frozen base commit `B`; the tasks are commits after
`B`, so the fix is not in the index. The query is the commit message verbatim.

Run:
    python experiments/bench_2026_11/run.py --split dev
    python experiments/bench_2026_11/run.py --split sealed --sealed

The sealed split refuses to run without `--sealed`, which is passed once per
release.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "xerj_2026_11"))
sys.path.insert(0, str(ROOT / "experiments" / "xerj_2026_11" / "evidence_gate"))
sys.stdout.reconfigure(encoding="utf-8")

from run_gate import _files, _invalid, _norm, _tools_for  # noqa: E402
from wilson import wilson  # noqa: E402

BASE = "7c2c7a3c6417539bc08f807d6790fe6e722d3a84"
CORPUS = Path(r"D:\Project\bench-B")
STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "when", "what",
    "where", "which", "have", "has", "not", "are", "was", "were", "will", "can",
    "all", "one", "two", "fix", "add", "update", "test", "tests", "code",
    "правка", "тесты", "код", "для", "что", "как", "или", "при",
}


def _tasks(split: str) -> list[dict]:
    rows = [json.loads(x) for x in (HERE / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if split == "all" or r["split"] == split]


def _solvable(task: dict) -> bool:
    """At least one gold file must exist in the corpus (PLAN Amendment 2)."""
    return any((CORPUS / g).is_file() for g in task["gold"])


def _kept_gold(task: dict) -> list[str]:
    return [g for g in task["gold"] if (CORPUS / g).is_file()]


def _corpus_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py", "*.md", "*.toml", "*.json"],
                         cwd=CORPUS, capture_output=True, text=True, encoding="utf-8")
    return sorted(x for x in out.stdout.splitlines() if x.strip())


class GrepBaseline:
    """Files ranked by how many distinct message terms they contain."""

    def __init__(self, files: list[str]):
        self.files = files
        self.texts = {}
        for path in files:
            try:
                self.texts[path] = (CORPUS / path).read_text(
                    encoding="utf-8", errors="ignore").lower()
            except OSError:
                self.texts[path] = ""

    def rank(self, message: str) -> list[str]:
        terms = {w for w in re.findall(r"[a-zA-Zа-яА-Я_]{4,}", message.lower())
                 if w not in STOP}
        if not terms:
            return []
        scored = []
        for path, text in self.texts.items():
            hits = sum(1 for term in terms if term in text)
            if hits:
                scored.append((-hits, path))
        scored.sort()
        return [path for _, path in scored]


def _hits(files: list[str], gold: list[str], k: int) -> bool:
    return any(any(g in f for f in files[:k]) for g in gold)


def _mrr(files: list[str], gold: list[str]) -> float:
    for rank, path in enumerate(files, 1):
        if any(g in path for g in gold):
            return 1.0 / rank
    return 0.0


def _stats(rows: list[dict], key: str) -> dict:
    top1 = sum(r[f"{key}_top1"] for r in rows)
    top5 = sum(r[f"{key}_top5"] for r in rows)
    any8 = sum(r[f"{key}_any8"] for r in rows)
    mrr = sum(r[f"{key}_mrr"] for r in rows) / len(rows)
    return {"n": len(rows), "top1": top1, "top5": top5, "any8": any8,
            "mrr": round(mrr, 3),
            "top5_ci": [round(x, 3) for x in wilson(top5, len(rows))]}


def _files_from_rows(rows: list[dict]) -> list[str]:
    out: list[str] = []
    for row in rows or []:
        meta = row.get("metadata") or {}
        file = str(meta.get("file") or row.get("file") or "")
        if file:
            file = file.replace("\\", "/")
            base = str(CORPUS).replace("\\", "/").rstrip("/")
            if file.startswith(base):
                file = file[len(base):].lstrip("/")
            out.append(file)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=("dev", "sealed", "all"))
    parser.add_argument("--sealed", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if args.split == "sealed" and not args.sealed:
        print("refused: sealed split needs --sealed (one run per release)")
        return 2
    if args.split == "all":
        print("refused: report dev and sealed separately")
        return 2

    tasks_all = _tasks(args.split)
    if args.limit:
        tasks_all = tasks_all[:args.limit]
    tasks = []
    for task in tasks_all:
        gold = _kept_gold(task)
        if gold:
            tasks.append({**task, "gold": gold})
    dropped = len(tasks_all) - len(tasks)
    print(f"split={args.split} tasks={len(tasks)} dropped_unsolvable={dropped} "
          f"corpus={CORPUS}", flush=True)

    tools = _tools_for({CORPUS})
    tool = tools[str(CORPUS)]

    # Guard: the corpus must be the frozen base, not a moving HEAD.
    from src.core.di_container import (  # noqa: E402
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )

    services = create_service_collection(CORPUS)
    indexer = services.resolve(ProjectIndexerRegistry).get_indexer(
        CORPUS, factory=services.resolve(IndexerFactoryKey)
    )
    head = indexer._symbol_index.graph.get_meta("build_head") or ""
    print(f"corpus build_head={head[:12]} expected={BASE[:12]}")
    baseline = GrepBaseline(_corpus_files())

    rows = []
    partial = HERE / f"results_{args.split}.partial.jsonl"
    done = set()
    if partial.is_file():
        for line in partial.read_text(encoding="utf-8").splitlines():
            if line.strip():
                old = json.loads(line)
                rows.append(old)
                done.add(old["id"])
        print(f"resuming: {len(done)} tasks already captured", flush=True)

    searcher = tool.resolve_searcher(explicit_project_root=str(CORPUS))
    for index, task in enumerate(tasks, 1):
        if task["id"] in done:
            continue
        text = asyncio.run(tool.execute(query=task["question"], limit=8,
                                        project_root=str(CORPUS)))
        files = _norm(_files(text), CORPUS)
        nb_text = asyncio.run(tool.execute(query=task["question"], limit=8,
                                           include_neighbours=True,
                                           project_root=str(CORPUS)))
        nb_files = _norm(_files(nb_text), CORPUS)
        grep = baseline.rank(task["question"])
        raw = asyncio.run(
            searcher.hybrid_search_async(task["question"], limit=50, rerank=False)
        )
        search_files = _files_from_rows(raw)
        row = {
            "id": task["id"],
            "valid": not _invalid(text),
            "tool_top1": _hits(files, task["gold"], 1),
            "tool_top5": _hits(files, task["gold"], 5),
            "tool_any8": _hits(files, task["gold"], 8),
            "tool_mrr": _mrr(files, task["gold"]),
            "neighbours_top1": _hits(nb_files, task["gold"], 1),
            "neighbours_top5": _hits(nb_files, task["gold"], 5),
            "neighbours_any8": _hits(nb_files, task["gold"], 8),
            "neighbours_mrr": _mrr(nb_files, task["gold"]),
            "search_top1": _hits(search_files, task["gold"], 1),
            "search_top5": _hits(search_files, task["gold"], 5),
            "search_any8": _hits(search_files, task["gold"], 8),
            "search_mrr": _mrr(search_files, task["gold"]),
            "grep_top1": _hits(grep, task["gold"], 1),
            "grep_top5": _hits(grep, task["gold"], 5),
            "grep_any8": _hits(grep, task["gold"], 8),
            "grep_mrr": _mrr(grep, task["gold"]),
            "files": files[:3],
        }
        rows.append(row)
        with partial.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  {index:>3}/{len(tasks)} {task['id']} "
              f"tool@5={row['tool_top5']} nb@5={row['neighbours_top5']} "
              f"search@5={row['search_top5']}", flush=True)

    invalid = sum(1 for r in rows if not r["valid"])
    stats = {arm: _stats(rows, arm) for arm in ("tool", "neighbours", "search", "grep")}
    only_tool = sum(1 for r in rows if r["neighbours_top5"] and not r["search_top5"])
    only_search = sum(1 for r in rows if r["search_top5"] and not r["neighbours_top5"])

    print(f"\n{'arm':<6} {'n':>3} {'hit@1':>6} {'hit@5':>6} {'any@8':>6} "
          f"{'MRR':>5}   hit@5 95% CI")
    for arm in ("tool", "neighbours", "search", "grep"):
        cell = stats[arm]
        print(f"{arm:<6} {cell['n']:>3} {cell['top1']:>6} {cell['top5']:>6} "
              f"{cell['any8']:>6} {cell['mrr']:>5}   {cell['top5_ci']}")
    print(f"\npaired hit@5: neighbours-only={only_tool} search-only={only_search} "
          f"delta={only_tool - only_search:+d}")
    print(f"invalid runs: {invalid}")
    if dropped:
        total = len(tasks) + dropped
        print(f"\nfull panel (dropped {dropped} unsolvable tasks counted as misses):")
        for arm in ("tool", "neighbours", "search", "grep"):
            cell = stats[arm]
            print(f"  {arm:<6} hit@1={cell['top1']}/{total} "
                  f"hit@5={cell['top5']}/{total} any@8={cell['any8']}/{total}")

    out = HERE / f"results_{args.split}.json"
    out.write_text(json.dumps({
        "split": args.split, "tasks": len(tasks), "dropped_unsolvable": dropped,
        "corpus_head": head, "stats": stats,
        "paired_hit5": {"tool_only": only_tool, "search_only": only_search},
        "invalid": invalid,
    }, ensure_ascii=False, indent=1), encoding="utf-8", newline="")

    if invalid:
        print("ABORT: a task did not run; the denominator is not the panel.")
        return 3
    if head[:12] != BASE[:12]:
        print("ABORT: corpus is not the frozen base commit.")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
