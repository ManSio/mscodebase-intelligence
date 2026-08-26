"""E3 — Category router evaluation on tasks_v3.json (real index, read-only).

Compares three search strategies against 30 labeled tasks (klass taxonomy,
GT file + required_facts):
  A: fast only
  B: quality only
  C: cascade fast -> quality (only when fast misses), with latency budget

Scoring: GT-file hit in top-K (K=5); required_facts coverage by pattern match
(case-insensitive substring / regex) across top-K snippets. Per-klass aggregates:
recall@K, fact coverage, latency p50/p95, wrong_patterns leak.

Read-only: opens the REAL project DB via get_db_path(); never writes/rebuilds.
Run (project venv or EXT venv):
  python experiments/mech_orch/E3_category_router_eval.py [--topk 5] [--limit 8]
"""
import asyncio
import json
import os
import re
import statistics
import sys
import time
import traceback
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXT = Path(os.getenv("EXT_ROOT", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
if str(EXT) not in sys.path:
    sys.path.insert(0, str(EXT))

try:
    from dotenv import load_dotenv
    env = PROJECT_ROOT / ".env"
    if env.exists():
        load_dotenv(env)
except ImportError:
    pass

os.environ.setdefault("PYTHONPATH", str(EXT))
os.environ["PROJECT_PATH"] = str(PROJECT_ROOT)
# Deterministic: use the ALREADY RUNNING llama-server (8080 embedder / 8081 reranker),
# NOT auto-detect (fails in standalone -> ONNX fallback -> embedder dead).
os.environ["LLAMA_CPP_ENABLED"] = "true"

import logging
logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

from src.config.settings import get_config
from src.core.artifact_paths import get_db_path
from src.providers.embedder.remote_embedder import RemoteEmbedder
from src.core.indexing.file_guard import FileGuard
from src.core.indexing.indexer import Indexer
from src.core.search.engine import Searcher
from src.core.di_container import create_service_collection
from src.core.indexing.parser import CodeParser
from src.core.indexing.symbol_index import SymbolIndex

TOP_K = int(os.getenv("E3_TOPK", "5"))
LIMIT = int(os.getenv("E3_LIMIT", "8"))
TASKS_FILE = PROJECT_ROOT / "experiments" / "context_engine" / "tasks_v3.json"
OUT_FILE = PROJECT_ROOT / "experiments" / "mech_orch" / "results_E3_router.json"


def norm(p: str) -> str:
    return str(p).replace("\\", "/").lower()


def gt_hit(files: list, gt: str) -> bool:
    g = norm(gt)
    for f in files:
        fn = norm(f)
        if fn == g or fn.endswith(g) or g.endswith(fn.split("/")[-1]):
            return True
    return False


def fact_covered(facts: list, snippets_text: str) -> tuple:
    text = snippets_text.lower()
    covered = 0
    for fct in facts:
        pat = str(fct.get("pattern", "") or "")
        if not pat:
            continue
        try:
            if re.search(pat, text, flags=re.IGNORECASE):
                covered += 1
        except re.error:
            if pat.lower() in text:
                covered += 1
    return covered, len(facts)


def build_stack():
    services = create_service_collection(PROJECT_ROOT)
    embedder = services.resolve(RemoteEmbedder)
    # llama-server уже запущен (проверено curl) — force-режим вместо авто-детекта,
    # который в standalone-процессе уходит в ONNX-fallback (артефакт среды).
    if hasattr(embedder, "_check_llama_cpp") and embedder._check_llama_cpp():
        embedder.mode = "llama_cpp"
        print("[*] embedder: forced mode=llama_cpp (live server 8080)")
    else:
        print("[!] embedder: llama_cpp NOT reachable — results will be degraded")
    db_path = get_db_path(PROJECT_ROOT)  # REAL index (read-only usage)
    file_guard = FileGuard(PROJECT_ROOT)
    parser = CodeParser()
    symbol_index = SymbolIndex()
    indexer = Indexer(
        db_path=db_path, embedder=embedder, file_guard=file_guard,
        project_path=PROJECT_ROOT, parser=parser, symbol_index=symbol_index,
    )
    searcher = Searcher(indexer, embedder)
    indexer.set_searcher(searcher)
    return searcher, db_path


def files_of(res: list) -> list:
    out = []
    for r in res:
        meta = r.get("metadata") or {}
        f = meta.get("file") or r.get("file") or "unknown"
        out.append(str(f))
    return out


def snippets_of(res: list, topk: int = TOP_K) -> str:
    parts = []
    for r in res[:topk]:
        parts.append(str(r.get("text_full") or r.get("text") or ""))
    return "\n".join(parts)


async def run_one(searcher, task, mode: str) -> dict:
    q = task.get("prompt") or task.get("query") or ""
    t0 = time.perf_counter()
    try:
        out = searcher.search_with_mode(q, mode=mode, limit=LIMIT)
    except Exception as e:
        return {"mode": mode, "error": str(e), "latency_ms": (time.perf_counter() - t0) * 1000}
    latency = (time.perf_counter() - t0) * 1000
    tinfo = out.get("timing_ms") or {}
    results = out.get("results") or []
    files = files_of(results)[:TOP_K]
    facts_text = snippets_of(results)
    return {
        "mode": mode,
        "latency_ms": latency,
        "server_total_ms": tinfo.get("total_ms"),
        "n_results": len(results),
        "files": files,
        "results": results,  # local-only: stripped before saving to JSON
    }


async def main():
    tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))["tasks"]
    print(f"[*] tasks={len(tasks)} topk={TOP_K} limit={LIMIT}")

    searcher, db_path = build_stack()
    # sanity: real index must be non-empty
    try:
        n = 0
        if searcher.indexer and searcher.indexer.table is not None:
            n = searcher.indexer.table.count_rows()
        print(f"[*] real DB: {db_path}")
        print(f"[*] index rows: {n}")
        if n == 0:
            print("[!] Index empty — abort (run reindex first)")
            return
    except Exception as e:
        print(f"[!] cannot read index: {e}")
        return

    rows = []
    for i, t in enumerate(tasks, 1):
        tid = t["id"]
        klass = t.get("klass", "?")
        gt = t.get("file", "")
        facts = t.get("required_facts", [])
        fast = await run_one(searcher, t, "fast")
        quality = await run_one(searcher, t, "quality")

        fh = gt_hit(fast.get("files", []), gt)
        qh = gt_hit(quality.get("files", []), gt)
        # cascade arm: fast first; quality only on fast miss
        cascade_files = fast.get("files", []) if fh else quality.get("files", [])
        cascade_mode = "fast" if fh else "quality"
        cascade_lat = fast.get("latency_ms", 0) + (0 if fh else quality.get("latency_ms", 0))
        ch = gt_hit(cascade_files, gt)

        facts_text_fast = snippets_of(fast.get("results", []))
        facts_text_qual = snippets_of(quality.get("results", []))
        fc_fast, nf = fact_covered(facts, facts_text_fast)
        fc_qual, _ = fact_covered(facts, facts_text_qual)
        fc_casc = fc_fast if fh else fc_qual

        # strip chunk bodies before persisting
        fast_row = {k: v for k, v in fast.items() if k != "results"}
        qual_row = {k: v for k, v in quality.items() if k != "results"}

        rows.append({
            "id": tid, "klass": klass, "gt": gt,
            "fast": {**fast_row, "hit": fh, "facts": fc_fast, "facts_n": nf},
            "quality": {**qual_row, "hit": qh, "facts": fc_qual, "facts_n": nf},
            "cascade": {"hit": ch, "mode": cascade_mode, "latency_ms": cascade_lat, "facts": fc_casc, "facts_n": nf},
        })
        d = rows[-1]
        print(f"{tid:4} {klass:16} fast={'H' if fh else '-':1}{fast.get('latency_ms',0):7.0f}ms "
              f"qual={'H' if qh else '-':1}{quality.get('latency_ms',0):7.0f}ms "
              f"casc={'H' if ch else '-':1}{cascade_lat:7.0f}ms")

    # aggregates
    def agg(arm):
        hits = [r[arm]["hit"] for r in rows]
        lat = [r[arm].get("latency_ms", 0) for r in rows if r[arm].get("error") is None]
        fcov = [r[arm]["facts"] / max(r[arm]["facts_n"], 1) for r in rows if r[arm]["facts_n"]]
        return {
            "recall_k": round(sum(hits) / len(hits), 3),
            "facts_coverage_mean": round(statistics.mean(fcov), 3) if fcov else None,
            "latency_median_ms": round(statistics.median(lat), 1) if lat else None,
            "latency_p95_ms": round(sorted(lat)[int(len(lat) * 0.95) - 1], 1) if len(lat) > 1 else None,
        }

    by_klass = {}
    for kl in sorted(set(r["klass"] for r in rows)):
        kr = [r for r in rows if r["klass"] == kl]
        by_klass[kl] = {
            "n": len(kr),
            "fast_recall": round(sum(r["fast"]["hit"] for r in kr) / len(kr), 3),
            "quality_recall": round(sum(r["quality"]["hit"] for r in kr) / len(kr), 3),
            "cascade_recall": round(sum(r["cascade"]["hit"] for r in kr) / len(kr), 3),
        }

    report = {"topk": TOP_K, "n": len(rows), "arms": {a: agg(a) for a in ("fast", "quality", "cascade")}, "by_klass": by_klass, "rows": rows}
    OUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== ARMS ===")
    for a in ("fast", "quality", "cascade"):
        print(f"{a:8}: {report['arms'][a]}")
    print("\n=== BY KLASS ===")
    for kl, v in by_klass.items():
        print(f"{kl:18}: n={v['n']:2} fast={v['fast_recall']:.2f} quality={v['quality_recall']:.2f} cascade={v['cascade_recall']:.2f}")
    print(f"\n[*] saved: {OUT_FILE}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)