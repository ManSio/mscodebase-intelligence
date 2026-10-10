#!/usr/bin/env python3
# -*- coding: utf-8
"""E27 замер: BM25-плечи RD1 (raw+desc), RD2 (aug+desc), D (desc-only).
Формула/сегментация/запросы — те же, что E26 (импорт, без дрейфа).
DESC-<шаблон>: "DESC: {описание}" строкой после FILE (RD1) / после AUG-блока (RD2).
USAGE: python experiments/e27_doc2query/e27_measure.py --out experiments/e27_doc2query/results/e27.json
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "e26_ast"))
sys.path.insert(0, str(ROOT / "experiments" / "embeddinggemma2_eval"))
from e26_bm25 import build_index, search, score_file_chunk, segment, augment  # noqa: E402
from bench_e18 import GOLD_FILES, DISTRACTORS  # noqa: E402

EXP27 = ROOT / "experiments" / "e27_doc2query"
FROZEN_Q = ROOT / "experiments" / "embeddinggemma2_eval" / "frozen" / "QUERIES.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    desc = json.loads((EXP27 / "results" / "descriptions.json").read_text(encoding="utf-8"))
    if not desc:
        print("FATAL: no descriptions", file=sys.stderr)
        sys.exit(2)
    rows = [json.loads(l) for l in FROZEN_Q.read_text(encoding="utf-8").splitlines() if l.strip()]
    scored = [q for q in rows if q["type"] in ("gold", "positive")]
    if not scored:
        print("FATAL: no queries", file=sys.stderr)
        sys.exit(2)
    files = sorted(set(GOLD_FILES) | set(DISTRACTORS))
    arms = {"RD1": [], "RD2": [], "D": []}
    chunk_files = []
    for f in files:
        p = ROOT / f
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        rel = f.replace("\\", "/")
        d = desc.get(rel, {}).get("desc", "")
        for i, seg in enumerate(segment(body)):
            cid = f"{rel}#{i}"
            chunk_files.append((cid, rel))
            arms["RD1"].append((cid, seg + f"\nDESC: {d}"))
            arms["RD2"].append((cid, augment(rel, body) + seg + f"\nDESC: {d}"))
            arms["D"].append((cid, f"FILE: {rel}\nDESC: {d}"))
    if not arms["RD1"]:
        print("FATAL: empty corpus", file=sys.stderr)
        sys.exit(2)
    id2file = dict(chunk_files)
    res = {"n_chunks": len(chunk_files), "n_queries": len(scored),
           "n_empty_desc": sum(1 for v in desc.values() if not v.get("desc"))}
    for key, texts in arms.items():
        w, ids = build_index(texts)
        ranked, exps = [], []
        for q in scored:
            ranked.append([id2file[cid] for cid, _ in search(w, ids, q["query"])])
            exps.append(q["expect"])
        s = score_file_chunk(ranked, None, exps)
        res[key] = {"hit@1_file": s["h1f"][1], "hit@5_file": s["h5f"][1],
                    "mrr_file": s["mrrf"][1], "per_query_h1f": s["h1f"][0]}
        print(f"[{key}] h1f={s['h1f'][1]:.3f} h5f={s['h5f'][1]:.3f} mrrf={s['mrrf'][1]:.3f}",
              flush=True)
    out = Path(args.out)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK -> {out}")


if __name__ == "__main__":
    main()
