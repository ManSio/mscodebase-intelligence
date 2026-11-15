"""B2: the same commit-localization benchmark on an external repository.

Nothing here is ours: the repo, its commit messages and its history were written
by other people. Same rule as B1 (PLAN.md): gold = the files the commit changed,
corpus at `--base` so the fix is not indexed.

Run:
    python experiments/bench_2026_11/external.py --repo D:\\Project\\bench-ext\\requests \
        --corpus D:\\Project\\bench-ext\\req-B --base e331a288 --limit 40
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

STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "when",
        "what", "where", "which", "have", "has", "not", "are", "was", "were"}


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    return out.stdout if out.returncode == 0 else ""


def _tasks(repo: Path, base: str, limit: int) -> list[dict]:
    raw = _git(repo, "log", f"{base}..HEAD", "--no-merges",
               "--format=%H%x00%ad%x00%B%x00", "--date=short")
    parts = raw.split("\x00")
    tasks = []
    for sha, date, message in zip(parts[0::3], parts[1::3], parts[2::3]):
        sha, message = sha.strip(), message.strip()
        files = [f for f in _git(repo, "show", "--name-only", "--format=", sha).splitlines() if f.strip()]
        if not files or len(files) > 20 or len(message) < 20:
            continue
        gold = sorted(f for f in files
                      if f.endswith(".py") and not f.startswith(("tests/", "docs/")))
        if not gold:
            continue
        tasks.append({"id": sha[:12], "sha": sha, "date": date,
                      "question": message, "gold": gold})
    tasks.sort(key=lambda t: (t["date"], t["id"]))
    return tasks[:limit] if limit else tasks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    repo, corpus = Path(args.repo), Path(args.corpus)
    corpus_head = _git(corpus, "rev-parse", "HEAD").strip()
    base_head = _git(repo, "rev-parse", f"{args.base}^{{commit}}").strip()
    if not corpus_head or corpus_head != base_head:
        print(
            f"ABORT: corpus HEAD {corpus_head[:12] or '?'} != base {base_head[:12] or '?'}"
            " — the fixes would already be in the index and the panel would measure itself",
            flush=True,
        )
        return 2
    tasks = _tasks(repo, args.base, args.limit)
    print(f"repo={repo.name} base={args.base[:12]} tasks={len(tasks)}", flush=True)

    tool = _tools_for({corpus})[str(corpus)]
    searcher = tool.resolve_searcher(explicit_project_root=str(corpus))
    texts = {}
    for path in _git(repo, "ls-files", "*.py").splitlines():
        try:
            texts[path] = (corpus / path).read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            texts[path] = ""

    def grep_rank(message: str) -> list[str]:
        terms = {w for w in re.findall(r"[a-zA-Z_]{4,}", message.lower()) if w not in STOP}
        if not terms:
            return []
        scored = [(-sum(1 for t in terms if t in text), path)
                  for path, text in texts.items()]
        return [p for score, p in sorted(scored) if score]

    def hits(files, gold, k):
        return any(any(g in f for f in files[:k]) for g in gold)

    rows = []
    for index, task in enumerate(tasks, 1):
        text = asyncio.run(tool.execute(query=task["question"], limit=8,
                                        project_root=str(corpus)))
        files = _norm(_files(text), corpus)
        nb = _norm(_files(asyncio.run(tool.execute(
            query=task["question"], limit=8, include_neighbours=True,
            project_root=str(corpus)))), corpus)
        raw = asyncio.run(searcher.hybrid_search_async(task["question"], limit=50, rerank=False))
        search = []
        for row in raw or []:
            meta = row.get("metadata") or {}
            f = str(meta.get("file") or row.get("file") or "").replace("\\", "/")
            if f.startswith(str(corpus).replace("\\", "/")):
                f = f[len(str(corpus).replace("\\", "/")).rstrip("/"):].lstrip("/")
            if f:
                search.append(f)
        grep = grep_rank(task["question"])
        rows.append({
            "id": task["id"],
            "valid": not _invalid(text),
            "tool": (hits(files, task["gold"], 1), hits(files, task["gold"], 5)),
            "neighbours": (hits(nb, task["gold"], 1), hits(nb, task["gold"], 5)),
            "search": (hits(search, task["gold"], 1), hits(search, task["gold"], 5)),
            "grep": (hits(grep, task["gold"], 1), hits(grep, task["gold"], 5)),
        })
        print(f"  {index:>3}/{len(tasks)} {task['id']} "
              f"tool@5={rows[-1]['tool'][1]} nb@5={rows[-1]['neighbours'][1]}", flush=True)

    n = len(rows)
    print(f"\n{'arm':<12} {'hit@1':>6} {'hit@5':>6}   hit@5 95% CI")
    table = {}
    for arm in ("tool", "neighbours", "search", "grep"):
        top1 = sum(1 for r in rows if r[arm][0])
        top5 = sum(1 for r in rows if r[arm][1])
        lo, hi = wilson(top5, n)
        table[arm] = {"top1": top1, "top5": top5}
        print(f"{arm:<12} {top1:>6} {top5:>6}   [{lo:.2f}, {hi:.2f}]")
    invalid = sum(1 for r in rows if not r["valid"])
    print(f"invalid runs: {invalid}")

    out = HERE / f"results_external_{repo.name}.json"
    out.write_text(json.dumps({"repo": repo.name, "base": args.base,
                               "tasks": n, "table": table,
                               "invalid": invalid}, ensure_ascii=False, indent=1),
                   encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
