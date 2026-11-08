"""E2-lite: does the `search`-channel fix hold on OTHER projects?

Two pinned external repos (see frozen/gold_external.json), 12 tasks:
definitions with a re-export decoy in `__init__.py`, and caller questions.
Same two arms and the same top-10 file rule as E1, so the numbers are
comparable; the corpus is different, which is the point (§19.24).

Each repo is indexed into its own artifact store (outside the project), then
queried in-process: the CLI bridge cannot run project-scoped tools, and the MCP
host only reloads code on a restart.

Run: python experiments/xerj_2026_11/run_external.py [--skip-index]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_GOLD = HERE / "frozen" / "gold_external.json"
GOLD_FILE = DEFAULT_GOLD
RAW_FILE = HERE / "external_raw.txt"
JSON_FILE = HERE / "external.json"
MAX_TOP = 10


def index_repo(project: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "reindex_text_only.py"),
         "--project", str(project), "--quiet"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
    )
    tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    print(f"  index {project.name}: rc={proc.returncode} {tail[0][:100]}")
    return proc.returncode == 0


def arm_a(project: Path, tokens: list[str]) -> dict:
    from src.core.indexing.file_guard import FileGuard

    guard = FileGuard(project)
    patterns = [re.compile(re.escape(t).encode("utf-8")) for t in tokens]
    files: list[str] = []
    started = time.perf_counter()
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = sorted(d for d in dirnames if d != ".git" and not guard.should_skip_dir(d))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix != ".py" or guard.should_skip_file(path):
                continue
            try:
                source = path.read_bytes()
            except OSError:
                continue
            if not any(p.search(source) for p in patterns):
                continue
            rel = path.relative_to(project).as_posix()
            if rel not in files:
                files.append(rel)
    return {"files": files[:MAX_TOP], "elapsed_s": round(time.perf_counter() - started, 2)}


def main() -> int:
    global GOLD, GOLD_FILE, RAW_FILE, JSON_FILE
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--gold", default=str(DEFAULT_GOLD),
                        help="frozen gold set (default: gold_external.json)")
    parser.add_argument("--tag", default="",
                        help="suffix for the output files (e.g. v2)")
    args = parser.parse_args()
    GOLD_FILE = Path(args.gold)
    GOLD = json.loads(GOLD_FILE.read_text(encoding="utf-8"))
    if args.tag:
        RAW_FILE = HERE / f"external_{args.tag}_raw.txt"
        JSON_FILE = HERE / f"external_{args.tag}.json"
    print(f"gold: {GOLD_FILE.name} -> {JSON_FILE.name}")

    from src.core.di_container import (  # noqa: E402
        IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
    )
    from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: E402

    services = create_service_collection(ROOT)
    registry = services.resolve(ProjectIndexerRegistry)
    factory = services.resolve(IndexerFactoryKey)
    tool = InvestigateTool(services)

    raw: list[str] = []
    results: list[dict] = []
    try:
        for repo in GOLD["repos"]:
            project = Path(repo["path"])
            if not project.is_dir():
                print(f"MISSING {project} — run fetch_external.py first")
                return 2
            print(f"\n=== {repo['slug']} @ {repo['pin']}")
            if not args.skip_index and not index_repo(project):
                print("  INDEX FAILED — skipping corpus (no partial numbers)")
                continue
            registry.get_indexer(project, factory=factory)
            for task in repo["tasks"]:
                tokens = re.findall(r"`([^`]+)`", task["question"])[:2]
                a = arm_a(project, tokens)
                started = time.perf_counter()
                text = asyncio.run(tool.execute(query=task["question"], limit=8,
                                                project_root=str(project)))
                elapsed = time.perf_counter() - started
                rows = re.findall(r"^(\d+)\. (.+?):(\d+)", text, re.M)
                b_files = [p.replace("\\", "/").split(f"{repo['slug']}/")[-1] for _r, p, _l in rows]
                invalid = '"ok": false' in text[:300] or "Timeout after" in text
                def hit(files):
                    return any(any(g.endswith(f) for f in files) for g in task["gold"])

                a_ok = hit(a["files"])
                b_ok = None if invalid else hit(b_files)
                # Rank-1 is the metric that matters on small corpora: with 8
                # files "gold in top-10" is always true. It is also the metric
                # XERJ quotes (correct-file@1).
                a_top1 = bool(a["files"]) and hit(a["files"][:1])
                b_top1 = None if invalid else (bool(b_files) and hit(b_files[:1]))
                degraded = re.search(r"degraded: ([^\n]+)", text)
                row = {
                    "repo": repo["slug"], "id": task["id"], "kind": task["kind"],
                    "question": task["question"], "gold": task["gold"],
                    "a_files": a["files"], "a_ok": a_ok, "a_top1": a_top1,
                    "b_files": b_files[:MAX_TOP], "b_ok": b_ok, "b_top1": b_top1,
                    "b_invalid": invalid,
                    "b_elapsed_s": round(elapsed, 2),
                    "degraded": degraded.group(1).strip() if degraded else "",
                    "b_text": text,
                }
                results.append(row)
                raw.append(
                    f"### {repo['slug']} {task['id']} {task['question']}\n"
                    f"A({a['elapsed_s']}s, ok={a_ok}): {a['files']}\n"
                    f"B({row['b_elapsed_s']}s, ok={b_ok}, degraded={row['degraded'] or '-'}): "
                    f"{b_files[:MAX_TOP]}\ngold: {task['gold']}\n--- B raw ---\n{text}\n"
                )
                print(f"  {task['id']} A={'Y' if a_ok else 'n'}/{'Y' if a_top1 else 'n'} "
                      f"B={'-' if b_ok is None else ('Y' if b_ok else 'n')}"
                      f"/{'-' if b_top1 is None else ('Y' if b_top1 else 'n')} "
                      f"{row['b_elapsed_s']:5.1f}s {row['degraded']}")
    finally:
        shutdown = getattr(services, "shutdown", None)
        if callable(shutdown):
            try:
                asyncio.run(shutdown())
            except Exception:
                pass

    RAW_FILE.write_text("\n".join(raw), encoding="utf-8", newline="")
    JSON_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8", newline="")

    print("\n=== summary")
    for kind in ("definition", "callers"):
        group = [r for r in results if r["kind"] == kind]
        valid = [r for r in group if r["b_ok"] is not None]
        if not group:
            continue
        a = sum(r["a_ok"] for r in group) / len(group)
        b = sum(bool(r["b_ok"]) for r in valid) / len(valid) if valid else float("nan")
        a1 = sum(r["a_top1"] for r in group) / len(group)
        b1 = (sum(bool(r["b_top1"]) for r in valid) / len(valid)) if valid else float("nan")
        print(f"{kind:<11} n={len(group):<3} valid={len(valid):<3} "
              f"A top10={a:.3f} B top10={b:.3f} | A #1={a1:.3f} B #1={b1:.3f}")
    for repo in GOLD["repos"]:
        group = [r for r in results if r["repo"] == repo["slug"]]
        valid = [r for r in group if r["b_ok"] is not None]
        if not group:
            continue
        a = sum(r["a_ok"] for r in group) / len(group)
        b = sum(bool(r["b_ok"]) for r in valid) / len(valid) if valid else float("nan")
        a1 = sum(r["a_top1"] for r in group) / len(group)
        b1 = (sum(bool(r["b_top1"]) for r in valid) / len(valid)) if valid else float("nan")
        print(f"{repo['slug']:<11} n={len(group):<3} valid={len(valid):<3} "
              f"A top10={a:.3f} B top10={b:.3f} | A #1={a1:.3f} B #1={b1:.3f}")
    for r in results:
        if r["b_ok"] is False:
            print(f"  miss {r['id']}: gold={r['gold']} got={r['b_files'][:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
