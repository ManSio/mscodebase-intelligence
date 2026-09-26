#!/usr/bin/env python3
"""F5 (4A) — retrieval arms A/B/C/D over the live index (read-only).

Design (frozen in experiments/4A_unit_of_return/README.md §1):
  A  top-k chunks            (current deploy)   baseline
  B  top-1 whole document     (unit under test) hypothesis
  C  oracle file, chunked      (gold file)       ceiling
  D  nothing                   (closed book)     control

Only the unit of return differs; retriever, mode, limit and query set are
fixed. This harness measures the OBJECTIVE side (does the returned unit
contain the gold file / is the top-1 doc gold) and emits per-arm context
bundles for the judged reader arm (separate step).

Read-only: opens the existing index (waits for the live MCP PID-lock), never
writes chunks. Population split (`code` vs `prose`) is data, set in the
queries file BEFORE looking at results.

Usage:
    python scripts/f5_retrieve_arms.py --queries <queries.jsonl> --out <out.json> \
        [--mode quality] [--limit 10] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = Path(os.getenv("EXT_ROOT", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
for _p in (str(EXT), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("PYTHONPATH", str(EXT))
os.environ["PROJECT_PATH"] = str(ROOT)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

MODE = "quality"
LIMIT = 10


def _wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def _load_queries(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(json.loads(s))
    return out


def _make_searcher():
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
    indexer = Indexer(db_path=get_db_path(ROOT), embedder=embedder,
                      file_guard=FileGuard(ROOT), project_path=ROOT,
                      parser=CodeParser(), symbol_index=SymbolIndex())
    return Searcher(indexer, embedder), indexer


def _read_whole(path: str) -> str:
    fp = ROOT / path
    try:
        return fp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("./")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default=MODE)
    ap.add_argument("--limit", type=int, default=LIMIT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    queries = _load_queries(Path(args.queries))
    print(f"f5: {len(queries)} queries, mode={args.mode} limit={args.limit}")
    if args.dry_run:
        for q in queries[:3]:
            print(f"  [{q['id']}] pop={q.get('population')} gold={q.get('gold_file')} q={q['question'][:70]}")
        print("DRY-RUN OK (search not called).")
        return 0

    searcher, indexer = _make_searcher()
    records = []
    for q in queries:
        gold = _norm(q.get("gold_file", ""))
        out = searcher.search_with_mode(q["question"], mode=args.mode, limit=args.limit)
        res = out.get("results", [])
        files = [_norm((r.get("metadata") or {}).get("file", "")) for r in res]
        # Arm A: top-k chunks
        a_hit1 = bool(files) and files[0] == gold
        a_hit3 = gold in files[:3]
        a_hitk = gold in files
        # Arm B: whole top-1 doc
        b_top1 = files[0] if files else ""
        b_hit = b_top1 == gold
        # Arm C: oracle (gold file chunked) — ceiling by construction
        c_len = len(_read_whole(gold)) if gold else 0
        rec = {
            "id": q["id"], "population": q.get("population"), "gold_file": gold,
            "returned_files": files[:args.limit],
            "A_chunks": {"hit@1": a_hit1, "hit@3": a_hit3, f"hit@{args.limit}": a_hitk,
                         "context_chars": sum(len(r.get("text", "")) for r in res)},
            "B_whole_doc": {"top1_file": b_top1, "hit": b_hit, "context_chars": len(_read_whole(b_top1)) if b_top1 else 0},
            "C_oracle": {"hit": bool(gold), "context_chars": c_len},
            "D_closed_book": {"hit": False, "context_chars": 0},
        }
        records.append(rec)
        print(f"  [{q['id']}] gold={gold[-50:]:50s} A.hit1={a_hit1} A.hit3={a_hit3} B={b_hit}")

    def rate(key: str, field: str) -> dict:
        k = sum(1 for r in records if r[key][field])
        return {"k": k, "n": len(records), "rate": round(k / len(records), 4) if records else 0.0,
                "ci95": _wilson(k, len(records))}

    summary = {
        "queries": len(records), "mode": args.mode, "limit": args.limit,
        "populations": sorted({r["population"] for r in records if r["population"]}),
        "metrics": {
            "A_hit@1": rate("A_chunks", "hit@1"),
            "A_hit@3": rate("A_chunks", "hit@3"),
            f"A_hit@{args.limit}": rate("A_chunks", f"hit@{args.limit}"),
            "B_top1_is_gold": rate("B_whole_doc", "hit"),
            "C_oracle": rate("C_oracle", "hit"),
            "D_closed_book": rate("D_closed_book", "hit"),
        },
        "avg_context_chars": {
            "A": round(sum(r["A_chunks"]["context_chars"] for r in records) / len(records)) if records else 0,
            "B": round(sum(r["B_whole_doc"]["context_chars"] for r in records) / len(records)) if records else 0,
            "C": round(sum(r["C_oracle"]["context_chars"] for r in records) / len(records)) if records else 0,
            "D": 0,
        },
        "records": records,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    m = summary["metrics"]
    print(f"\nA hit@1={m['A_hit@1']['rate']} hit@3={m['A_hit@3']['rate']} hit@{args.limit}={m[f'A_hit@{args.limit}']['rate']}")
    print(f"B top1-is-gold={m['B_top1_is_gold']['rate']}  C oracle={m['C_oracle']['rate']}  D={m['D_closed_book']['rate']}")
    print(f"avg ctx chars: A={summary['avg_context_chars']['A']} B={summary['avg_context_chars']['B']} C={summary['avg_context_chars']['C']}")
    print(f"-> {out_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(1)
