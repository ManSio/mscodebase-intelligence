#!/usr/bin/env python3
"""F5 judged reader arm: does the unit of return help the READER answer?

Design (README §1, RESEARCH deltas §9, judge-confound §10):
  - Reader gets the arm's context (A top-k chunks / B whole top-1 doc /
    C oracle gold doc / D empty) + the question; answers 1-3 sentences.
  - Judge is a DIFFERENT model (no self-grading), sees ONLY: question +
    identical reference (gold evidence_span) + the candidate answer under an
    opaque token. It never sees the arm name.
  - Majority over --trials; --judge-repeats measures judge stability.

Runs via the opencode CLI (same mechanism as F4b), but parallel across
(query, arm) units like scripts/f4b_run_all.py. A silent opencode fallback to
another model is REJECTED (channel #1 guard), not graded.

Usage:
    python scripts/f5_judged_run.py --outdir <dir> --dry-run
    python scripts/f5_judged_run.py --outdir <dir> --ids F5S-01,F5S-09 \
        --arms A,B,C,D --trials 3 --parallel 8 --timeout 400
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
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
BUILD_MODEL = re.compile(r"build\s*[·>\-:]+\s*([A-Za-z0-9._/\-]+)")
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
    # Windows: a multi-line argv prompt makes opencode.cmd hang / fall back to a
    # default model. Keep the CLI prompt single-line (F4b did the same).
    prompt = " ".join(prompt.split())
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
    text = ANSI.sub("", raw.decode("utf-8", errors="replace"))
    # Channel #1 guard: a silent opencode fallback to another model corrupts the
    # experiment. Reject rather than record a wrong-model answer.
    if "Cannot connect" in text or "Error:" in text:
        return "[ERROR] " + text
    m = BUILD_MODEL.search(text)
    want = model.split("/")[-1]
    if m and m.group(1) and want not in m.group(1):
        return f"[MODEL-MISMATCH:{m.group(1)}] " + text
    return text


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
    ap.add_argument("--ids", default="", help="comma list of query ids (overrides --n)")
    ap.add_argument("--arms", default="A,B,C,D")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--judge-repeats", type=int, default=1)
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--reader-model", default=READER_MODEL)
    ap.add_argument("--judge-model", default=JUDGE_MODEL)
    ap.add_argument("--timeout", type=int, default=400)
    ap.add_argument("--seed", type=int, default=42)
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
    workdir = (outdir / "work").resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "opencode.json").write_text(json.dumps({
        "mcp": {k: {"enabled": False} for k in
                ("mscodebase-intelligence", "msp-portfolio", "community-memory", "arclux")},
        "permission": {"edit": "deny", "bash": "deny", "webfetch": "deny",
                       "websearch": "deny", "external_directory": "deny"}}, indent=2), encoding="utf-8")

    rng = random.Random(args.seed)

    # Sequential pre-retrieval (Searcher holds the index lock read-only).
    contexts: dict[tuple[str, str], str] = {}
    if args.dry_run:
        results_by_q = {q["id"]: [] for q in queries}
    else:
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
        results_by_q = {}
        for q in queries:
            out = searcher.search_with_mode(q["question"], mode="quality", limit=10)
            results_by_q[q["id"]] = out.get("results", [])
    for q in queries:
        gold = _norm(q["gold_file"])
        for arm in arms:
            contexts[(q["id"], arm)] = _arm_context(arm, results_by_q[q["id"]], gold)

    bin_ = None if args.dry_run else _opencode_bin()

    def run_unit(q: dict, arm: str) -> dict:
        gold = _norm(q["gold_file"])
        ctx_file = (workdir / f"ctx_{q['id']}_{arm}.txt")
        ctx_file.write_text(contexts[(q["id"], arm)], encoding="utf-8")
        ctx_file = ctx_file.resolve()
        answers, verdicts = [], []
        for t in range(args.trials):
            if args.dry_run:
                answers.append("[DRY]")
                verdicts.append("uncertain")
                continue
            prompt = f"{READER_INSTR}\n\nQuestion: {q['question']}"
            a = _run(bin_, prompt, args.reader_model, workdir, [ctx_file], args.timeout)
            answers.append(a)
            (workdir / f"ans_{q['id']}_{arm}_{t}.txt").write_text(a, encoding="utf-8")
            if a.startswith("["):
                verdicts.append("invalid")
                continue
            ans_file = (workdir / f"ans_{q['id']}_{arm}_{t}.txt").resolve()
            vrep = []
            for _ in range(args.judge_repeats):
                jp = (f"{JUDGE_INSTR}\n\nQuestion: {q['question']}\n"
                      f"Reference answer: {q['evidence_span']}")
                jt = _run(bin_, jp, args.judge_model, workdir, [ans_file], args.timeout)
                vrep.append(_parse_verdict(jt))
            verdicts.append(vrep[0] if len(vrep) == 1 else max(set(vrep), key=vrep.count))
        return {"id": q["id"], "population": q.get("population"), "gold_file": gold,
                "reference": q["evidence_span"], "arm": arm,
                "answers": answers, "verdicts": verdicts}

    units = [(q, arm) for q in queries for arm in arms]
    rng.shuffle(units)  # randomized order (blind)
    records = []
    with cf.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        for res in ex.map(lambda u: run_unit(u[0], u[1]), units):
            records.append(res)
            print(f"  [{res['id']}] arm {res['arm']}: {res['verdicts']}", flush=True)

    # reassemble per query
    by_q: dict[str, dict] = {}
    for r in records:
        rec = by_q.setdefault(r["id"], {"id": r["id"], "population": r["population"],
                                        "gold_file": r["gold_file"], "reference": r["reference"],
                                        "arms": {}})
        rec["arms"][r["arm"]] = {"answers": r["answers"], "verdicts": r["verdicts"]}
    ordered = [by_q[q["id"]] for q in queries]

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "judged_raw.json").write_text(json.dumps(
        {"config": vars(args), "records": ordered}, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {}
    for arm in arms:
        vals = [v for r in ordered for v in r["arms"][arm]["verdicts"]]
        k = sum(1 for v in vals if v == "correct")
        inval = sum(1 for v in vals if v == "invalid")
        summary[arm] = {"correct": k, "n": len(vals), "invalid": inval,
                        "rate": round(k / len(vals), 4) if vals else 0}
    print("summary:", json.dumps(summary, ensure_ascii=False))
    print(f"-> {outdir / 'judged_raw.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
