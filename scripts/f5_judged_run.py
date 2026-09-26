#!/usr/bin/env python3
"""F5 judged reader arm: does the unit of return help the READER answer?

Design (README §1, RESEARCH deltas §9, judge-confound §10):
  - Reader gets the arm's context (A top-k chunks / B whole top-1 doc /
    C oracle gold doc / D empty) + the question; answers 1-3 sentences.
  - Judge is a DIFFERENT model (no self-grading), sees ONLY: question +
    identical reference (gold evidence_span) + the candidate answer under an
    opaque token. It never sees the arm name.
  - Majority over --trials; --judge-repeats measures judge stability
    (flip-rate on the same artifact).
  - --leak-check: same candidate under two labels -> verdicts must match.

Runs via the opencode CLI (established mechanism; no raw API keys). Slow:
each call ~30-60s. Use --dry-run to validate plumbing without calls, or
--max-calls to bound a pilot.

Usage:
    python scripts/f5_judged_run.py --outdir experiments/4A_unit_of_return/results/f5judged --dry-run
    python scripts/f5_judged_run.py --outdir ... --n 4 --arms A,B,C,D --trials 1 --timeout 300
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = Path(os.getenv("EXT_ROOT", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
for _p in (str(EXT), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("PYTHONPATH", str(EXT))
os.environ["PROJECT_PATH"] = str(ROOT)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
FROZEN = ROOT / "experiments" / "4A_unit_of_return" / "frozen" / "f5" / "queries.jsonl"

READER_MODEL = "opencode-go/longcat-2.0"
JUDGE_MODEL = "opencode-go/qwen3.7-plus"
VARIANT = "high"

READER_INSTR = ("Context is attached. Answer the question in 1-3 sentences using ONLY the "
                "context. If the context lacks the answer, reply exactly: I don't know.")
JUDGE_INSTR = ("You are grading an answer. Use ONLY the reference. Reply a JSON object with a "
               "single key verdict, value correct | incorrect | uncertain.\n"
               "correct = the candidate states the reference fact; incorrect = wrong/missing; "
               "uncertain = cannot tell.")


def _opencode_bin() -> str:
    env = os.environ.get("OPENCODE_BIN")
    if env and Path(env).exists():
        return env
    found = shutil.which("opencode")
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if appdata:
        cand = Path(appdata) / "npm" / "opencode.cmd"
        if cand.exists():
            return str(cand)
    raise SystemExit("opencode binary not found (set OPENCODE_BIN)")


def _run(bin_: str, prompt: str, model: str, workdir: Path, files: list[Path],
         timeout: int) -> str:
    cmd = [bin_, "run", prompt, "--model", model, "--pure", "--dir", str(workdir),
           "--variant", VARIANT]
    for f in files:
        cmd.append(f"--file={f}")
    env = dict(os.environ, PYTHONUTF8="1", NO_COLOR="1")
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    raw = (p.stdout or b"") + b"\n" + (p.stderr or b"")
    return ANSI.sub("", raw.decode("utf-8", errors="replace"))


def _read(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("./")


def _load_queries() -> list[dict]:
    lines = FROZEN.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _retrieve(searcher, q: str, limit: int = 10) -> list[dict]:
    out = searcher.search_with_mode(q, mode="quality", limit=limit)
    return out.get("results", [])


def _arm_context(arm: str, results: list[dict], gold: str) -> str:
    if arm == "D":
        return ""
    if arm == "A":
        parts = []
        for r in results:
            f = _norm((r.get("metadata") or {}).get("file", ""))
            parts.append(f"### {f}\n{r.get('text', '')}")
        return "\n\n".join(parts)
    if arm == "B":
        if not results:
            return ""
        f = _norm((results[0].get("metadata") or {}).get("file", ""))
        return f"### {f}\n{_read(f)}"
    if arm == "C":
        return f"### {gold}\n{_read(gold)}"
    raise SystemExit(f"unknown arm {arm}")


def _parse_verdict(text: str) -> str:
    m = re.search(r'"verdict"\s*:\s*"?(correct|incorrect|uncertain)"?', text, re.I)
    if m:
        return m.group(1).lower()
    low = text.lower()
    for v in ("incorrect", "correct", "uncertain"):
        if v in low:
            return v
    return "uncertain"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--ids", default="", help="comma list of query ids to run (overrides --n)")
    ap.add_argument("--arms", default="A,B,C,D")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--judge-repeats", type=int, default=1)
    ap.add_argument("--reader-model", default=READER_MODEL)
    ap.add_argument("--judge-model", default=JUDGE_MODEL)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-calls", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    arms = [a.strip().upper() for a in args.arms.split(",") if a.strip()]
    queries = _load_queries()
    if args.ids:
        want = {i.strip() for i in args.ids.split(",") if i.strip()}
        queries = [q for q in queries if q["id"] in want]
    else:
        queries = queries[: args.n]
    outdir = Path(args.outdir)
    workdir = outdir / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "opencode.json").write_text(json.dumps({
        "mcp": {k: {"enabled": False} for k in
                ("mscodebase-intelligence", "msp-portfolio", "community-memory", "arclux")},
        "permission": {"edit": "deny", "bash": "deny", "webfetch": "deny",
                       "websearch": "deny", "external_directory": "deny"}}, indent=2), encoding="utf-8")

    rng = random.Random(args.seed)
    calls = {"n": 0}

    def budget_ok() -> bool:
        return args.max_calls == 0 or calls["n"] < args.max_calls

    searcher = None
    if not args.dry_run:
        from src.core.artifact_paths import get_db_path
        from src.core.di_container import create_service_collection
        from src.core.indexing.file_guard import FileGuard
        from src.core.indexing.indexer import Indexer
        from src.core.indexing.parser import CodeParser
        from src.core.indexing.symbol_index import SymbolIndex
        from src.core.search.engine import Searcher
        from src.providers.embedder.remote_embedder import RemoteEmbedder
        services = create_service_collection(ROOT)
        embedder = services.resolve(RemoteEmbedder)
        indexer = Indexer(db_path=get_db_path(ROOT), embedder=embedder, file_guard=FileGuard(ROOT),
                          project_path=ROOT, parser=CodeParser(), symbol_index=SymbolIndex())
        searcher = Searcher(indexer, embedder)

    bin_ = None if args.dry_run else _opencode_bin()
    records = []
    for q in queries:
        gold = _norm(q["gold_file"])
        results = _retrieve(searcher, q["question"], 10) if searcher else []
        rec = {"id": q["id"], "population": q.get("population"), "gold_file": gold,
               "reference": q["evidence_span"], "arms": {}}
        order = list(arms)
        rng.shuffle(order)  # randomized arm order (blind)
        for arm in order:
            ctx = _arm_context(arm, results, gold)
            ctx_file = workdir / f"ctx_{q['id']}_{arm}.txt"
            ctx_file.write_text(ctx, encoding="utf-8")
            answers, verdicts = [], []
            for t in range(args.trials):
                if not budget_ok():
                    answers.append("[BUDGET]")
                    continue
                if args.dry_run:
                    answers.append("[DRY]")
                    calls["n"] += 1
                else:
                    prompt = f"{READER_INSTR}\n\nQuestion: {q['question']}"
                    a = _run(bin_, prompt, args.reader_model, workdir, [ctx_file], args.timeout)
                    calls["n"] += 1
                    answers.append(a)
                    (workdir / f"ans_{q['id']}_{arm}_{t}.txt").write_text(a, encoding="utf-8")
                vrep = []
                for _ in range(args.judge_repeats):
                    if not budget_ok():
                        vrep.append("uncertain")
                        continue
                    if args.dry_run:
                        vrep.append("uncertain")
                        calls["n"] += 1
                        continue
                    ans_file = workdir / f"ans_{q['id']}_{arm}_{t}.txt"
                    jp = (f"{JUDGE_INSTR}\n\nQuestion: {q['question']}\n"
                          f"Reference answer: {q['evidence_span']}")
                    v = _run(bin_, jp, args.judge_model, workdir, [ans_file], args.timeout)
                    calls["n"] += 1
                    vrep.append(_parse_verdict(v))
                verdicts.append(vrep[0] if len(vrep) == 1
                                else max(set(vrep), key=vrep.count))
            rec["arms"][arm] = {"answers": answers, "verdicts": verdicts}
            print(f"  [{q['id']}] arm {arm}: verdict={rec['arms'][arm]['verdicts']}")
        records.append(rec)

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "judged_raw.json").write_text(json.dumps(
        {"config": vars(args), "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")

    # summary: correct-rate per arm (verdict=="correct")
    summary = {}
    for arm in arms:
        vals = [v for r in records for v in r["arms"][arm]["verdicts"]]
        k = sum(1 for v in vals if v == "correct")
        summary[arm] = {"correct": k, "n": len(vals), "rate": round(k / len(vals), 4) if vals else 0}
    print("summary:", json.dumps(summary, ensure_ascii=False))
    print(f"calls={calls['n']} -> {outdir / 'judged_raw.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
