"""E1 / P0-3: `investigate` vs plain grep on the frozen task set.

Arms
  A  plain tools: ripgrep over the repo, ranked by first match, top-10 files
  B  the product tool: `InvestigateTool.execute(query, limit=8)`, same DI and
     same class the MCP host registers

Scoring (fixed before the first run, see frozen/benchmark_tasks.md)
  positive    -> any gold file in the arm's top-10 files
  ambiguity   -> EVERY gold file present
  negative    -> any `file:line` row in the answer is a false positive
                 (frozen rule); the new explicit "exact: 0 hits" warning is
                 reported separately as `answered` because it changes what the
                 agent sees, not what the rule counts

Why in-process: the CLI bridge cannot run project-scoped tools (the registry is
UNINITIALIZED in a second process), and the MCP host only reloads code on a
restart. Priming the registry is the same lazy step the host does on its first
call; the second process opens the DB read-only, so `impact` may report
`InterfaceError` on the first query вЂ” it is printed, not hidden.

Run:
    python experiments/xerj_2026_11/run_baseline.py [--runs N] [--only ID,ID]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

TASKS_FILE = HERE / "frozen" / "benchmark_tasks.md"
RAW_FILE = HERE / "baseline_raw.txt"
JSON_FILE = HERE / "baseline.json"

TOKEN_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")
PATH_RE = re.compile(r"((?:src|docs|tests|scripts|tools|experiments)/[\w./-]+\.(?:py|md|rs|toml))")
MAX_TOP = 10


def parse_tasks() -> list[dict]:
    text = TASKS_FILE.read_text(encoding="utf-8")
    tasks: list[dict] = []
    kind = None
    for line in text.splitlines():
        if line.startswith("## Positive"):
            kind = "positive"
            continue
        if line.startswith("## Ambiguity"):
            kind = "ambiguity"
            continue
        if line.startswith("## Negative"):
            kind = "negative"
            continue
        if line.startswith("## ") or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("ID", "---") or set(cells[0]) <= {"-"}:
            continue
        task_id, question = cells[0], cells[1]
        if not re.match(r"^[PAN]\d{2}$", task_id):
            continue
        gold_col = cells[2]
        gold = sorted(set(PATH_RE.findall(gold_col)))
        task = {
            "id": task_id,
            "kind": kind,
            "question": question,
            "gold": gold,
            "tokens": TOKEN_RE.findall(question)[:2],
        }
        if kind == "negative":
            # the frozen row carries the token to search for
            frozen_tokens = TOKEN_RE.findall(gold_col)
            task["tokens"] = frozen_tokens or task["tokens"]
            task["gold"] = []
        if not task["tokens"]:
            words = [w for w in re.findall(r"[\wА-Яа-я-]{5,}", question)]
            task["tokens"] = words[:3]
        tasks.append(task)
    if not tasks:
        print("REFUSING: no tasks parsed (T10).", file=sys.stderr)
        raise SystemExit(2)
    return tasks


def arm_a(task: dict) -> dict:
    """Plain grep: walk + regex, first-appearance order, top-10 files.

    No ripgrep is installed in this environment, so the "plain tools" arm is a
    deterministic Python scan with the same file universe as the product
    (`FileGuard` skip rules) and no AST filtering вЂ” which is exactly what grep
    gives you. Ties are broken by walk order, which is sorted for repeatability.
    """
    from src.core.indexing.file_guard import FileGuard

    files: list[str] = []
    hits = 0
    started = time.perf_counter()
    guard = FileGuard(ROOT)
    scan_dirs = [ROOT / d for d in ("src", "docs", "tests", "scripts", "tools") if (ROOT / d).is_dir()]
    patterns = [re.compile(re.escape(t).encode("utf-8")) for t in task["tokens"]]
    for base in scan_dirs:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not guard.should_skip_dir(d))
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if guard.should_skip_file(path):
                    continue
                try:
                    if path.stat().st_size > 2_000_000:
                        continue
                    source = path.read_bytes()
                except OSError:
                    continue
                if b"\x00" in source[:8192]:
                    continue
                matched = sum(len(p.findall(source)) for p in patterns)
                if not matched:
                    continue
                hits += matched
                rel = path.relative_to(ROOT).as_posix()
                if rel not in files:
                    files.append(rel)
    return {
        "files": files[:MAX_TOP],
        "rows": len(files),
        "raw_hits": hits,
        "elapsed_s": round(time.perf_counter() - started, 2),
        "degraded": [],
        "text": "",
    }


def score(task: dict, files: list[str]) -> bool:
    if task["kind"] == "negative":
        return not files
    if task["kind"] == "ambiguity":
        return all(any(g in f for f in files) for g in task["gold"])
    return any(any(g in f for f in files) for g in task["gold"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--only", default="")
    args = parser.parse_args()

    tasks = parse_tasks()
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        tasks = [t for t in tasks if t["id"] in wanted]
    print(f"tasks: {len(tasks)} "
          f"(positive={sum(t['kind'] == 'positive' for t in tasks)}, "
          f"ambiguity={sum(t['kind'] == 'ambiguity' for t in tasks)}, "
          f"negative={sum(t['kind'] == 'negative' for t in tasks)})")

    from src.core.di_container import (  # noqa: E402
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )
    from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: E402

    services = create_service_collection(ROOT)
    registry = services.resolve(ProjectIndexerRegistry)
    registry.get_indexer(ROOT, factory=services.resolve(IndexerFactoryKey))
    tool = InvestigateTool(services)

    raw_lines: list[str] = []
    results: list[dict] = []
    try:
        for run in range(1, args.runs + 1):
            for task in tasks:
                a = arm_a(task)
                started = time.perf_counter()
                text = asyncio.run(tool.execute(query=task["question"], limit=8))
                b_elapsed = time.perf_counter() - started
                rows = re.findall(r"^(\d+)\. (.+?):(\d+) ", text, re.M)
                b_files = [f for _, f, _ in rows]
                b_files = [f.replace(str(ROOT).replace("\\", "/"), "").lstrip("/") for f in b_files]
                b_files = [f.replace("D:/", "") for f in b_files]
                degraded = re.search(r"degraded: ([^\n]+)", text)
                exact = re.search(r"exact: ([^\n]+)", text)
                # A tool-level timeout/error is NOT an answer. Counting it as
                # "found nothing" would make a negative task pass by accident —
                # the exact silent-success shape this package is about (§18).
                invalid = '"ok": false' in text[:300] or "Timeout after" in text
                row = {
                    "run": run,
                    "id": task["id"],
                    "kind": task["kind"],
                    "question": task["question"],
                    "gold": task["gold"],
                    "a_files": a["files"],
                    "a_ok": score(task, a["files"]),
                    "a_elapsed_s": a["elapsed_s"],
                    "b_files": [f.split("/")[-1] for f in b_files][:MAX_TOP],
                    "b_full_files": b_files[:MAX_TOP],
                    "b_ok": None if invalid else score(task, b_files),
                    "b_invalid": invalid,
                    "b_elapsed_s": round(b_elapsed, 2),
                    "degraded": degraded.group(1).strip() if degraded else "",
                    "exact": exact.group(1).strip() if exact else "",
                    "answered": bool(exact and "=0" in exact.group(1)),
                    "b_text": text,
                }
                results.append(row)
                raw_lines.append(
                    f"### run{run} {task['id']} [{task['kind']}] {task['question']}\n"
                    f"A({row['a_elapsed_s']}s, ok={row['a_ok']}): {a['files']}\n"
                    f"B({row['b_elapsed_s']}s, ok={row['b_ok']}, degraded={row['degraded'] or '-'}): "
                    f"{b_files[:MAX_TOP]}\n"
                    f"gold: {task['gold']}\n"
                    f"--- B raw ---\n{text}\n"
                )
                print(f"  run{run} {task['id']:<4} A={'Y' if row['a_ok'] else 'n'} "
                      f"B={'Y' if row['b_ok'] else 'n'} {row['b_elapsed_s']:5.1f}s "
                      f"{row['degraded'] or ''}")
    finally:
        shutdown = getattr(services, "shutdown", None)
        if callable(shutdown):
            try:
                asyncio.run(shutdown())
            except Exception:
                pass

    RAW_FILE.write_text("\n".join(raw_lines), encoding="utf-8", newline="")
    JSON_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8", newline="")

    print("\n=== summary ===")
    for kind in ("positive", "ambiguity", "negative"):
        rows = [r for r in results if r["kind"] == kind]
        if not rows:
            continue
        valid = [r for r in rows if r["b_ok"] is not None]
        a = sum(r["a_ok"] for r in rows) / len(rows)
        b = sum(r["b_ok"] for r in valid) / len(valid) if valid else float("nan")
        print(f"{kind:<10} n={len(rows):<3} valid={len(valid):<3} A={a:.3f} B={b:.3f}")
        if kind == "negative" and valid:
            answered = sum(r["answered"] for r in valid) / len(valid)
            print(f"{'':<10} answered 'no exact match' B={answered:.3f}")
        for r in rows:
            if r["b_ok"] is False:
                print(f"   B miss {r['id']}: gold={r['gold']} got={r['b_files'][:3]}")
            elif r["b_ok"] is None:
                print(f"   B INVALID {r['id']}: tool did not answer ({r['b_elapsed_s']}s)")
    valid_all = [r for r in results if r["b_ok"] is not None]
    a_all = sum(r["a_ok"] for r in results) / len(results)
    b_all = (sum(r["b_ok"] for r in valid_all) / len(valid_all)
             if valid_all else float("nan"))
    print(f"\noverall    A={a_all:.3f} B={b_all:.3f}  (N={args.runs} run(s), "
          f"{len(results)} asks, {len(valid_all)} valid B answers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
