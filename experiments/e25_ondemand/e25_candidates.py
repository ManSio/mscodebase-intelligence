#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E25-A: кандидаты top-10 fused-порядка БЕЗ вектора и БЕЗ реранкера.
Тот же прод-путь (search_with_mode quality), серверы :8080/:8081 убиты заранее,
DISABLE_ONNX_FALLBACK=true. Сохраняет ПОЛНЫЕ top-10 (file+text) на запрос.
T10: 0 запросов -> exit(2); 0 кандидатов на запрос = recall-промах (пишем, не падаем).
USAGE: $env:DISABLE_ONNX_FALLBACK="true"; python experiments/e25_ondemand/e25_candidates.py --out ...
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import e2e_quality_search as H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    searcher = H.build_searcher(ROOT)
    out = {"top": args.top, "queries": []}
    if not H.CASES:
        print("FATAL: empty CASES", file=sys.stderr)
        sys.exit(2)
    for q, exp in H.CASES:
        t0 = time.perf_counter()
        try:
            res = searcher.search_with_mode(query=q, mode="quality", limit=args.top)
            results = res.get("results", []) if isinstance(res, dict) else (res or [])
        except Exception as e:
            print(f"QUERY FAIL (counts as recall miss): {q[:40]}: {type(e).__name__}",
                  flush=True)
            results = []
        dt = (time.perf_counter() - t0) * 1000
        cands = []
        for r in results[:args.top]:
            meta = r.get("metadata") or {}
            cands.append({"file": str(meta.get("file", "")),
                          "text": r.get("text_full") or r.get("text") or "",
                          "score": r.get("final_score")})
        want = H.norm(exp)
        rec = 0
        for i, c in enumerate(cands):
            if H.norm(c["file"]) == want or H.norm(c["file"]).endswith(want):
                rec = i + 1
                break
        n_empty = sum(1 for c in cands if not c["text"])
        print(f"recall_rank={rec or '-'} n_cand={len(cands)} empty_text={n_empty} "
              f"ms={dt:.0f} :: {q[:50]}", flush=True)
        out["queries"].append({"q": q, "exp": exp, "recall_rank": rec,
                               "ms": dt, "candidates": cands})
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    recs = [x["recall_rank"] for x in out["queries"]]
    print(f"RECALL@10 = {sum(1 for r in recs if r)}/{len(recs)}", flush=True)
    print(f"OK -> {p}")


if __name__ == "__main__":
    main()
