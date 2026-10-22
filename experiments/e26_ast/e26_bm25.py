#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E26: BM25 raw vs symbol-augmented — одна формула TF*IDF, два входных текста.

Формула — копия src/core/search/bm25.py: TF raw-count,
IDF = log((N-df+0.5)/(df+0.5)+1), score = sum(tf*idf), skip <=0, sort desc.
_tokenize импортируется из src.core.search.utils (дивергенция ноль).
Guard: синтетический exact-тест до455 измерения (exit 2 при расхождении).
T10: пустой корпус/запросы -> exit(2).
USAGE: python experiments/e26_ast/e26_bm25.py --out experiments/e26_ast/results/e26.json
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "embeddinggemma2_eval"))
from src.core.search.utils import _tokenize  # noqa: E402
from bench_e18 import GOLD_FILES, DISTRACTORS  # noqa: E402 (тот же корпус, без дрейфа)

RE_TOK = re.compile(r"\W+")
FROZEN_Q = ROOT / "experiments" / "embeddinggemma2_eval" / "frozen" / "QUERIES.jsonl"
DEF_RE = re.compile(r"^(def|class)\s+(\w+)", re.M)


def guard_formula():
    """Exact-проверка TF*IDF на ручном корпусе (считано вручную)."""
    docs = {"d1": "alpha beta alpha", "d2": "beta gamma", "d3": "gamma gamma gamma"}
    N = 3
    tf, df = {}, {}
    for did, t in docs.items():
        tf[did] = {}
        for tok in _tokenize(t, RE_TOK):
            tf[did][tok] = tf[did].get(tok, 0) + 1
        for tok in tf[did]:
            df[tok] = df.get(tok, 0) + 1
    w = {}
    for did in docs:
        w[did] = {}
        for tok, c in tf[did].items():
            w[did][tok] = c * math.log((N - df[tok] + 0.5) / (df[tok] + 0.5) + 1)
    # ручной счёт (IDF = log((N-df+0.5)/(df+0.5)+1), как bm25.py:131):
    # alpha df=1 -> log(2.5/1.5+1)=log(8/3); d1 tf=2
    assert abs(w["d1"]["alpha"] - 2 * math.log(8 / 3)) < 1e-9, w
    # beta/gamma df=2 -> log(1.5/2.5+1)=log(1.6); d3 gamma tf=3
    assert abs(w["d3"]["gamma"] - 3 * math.log(1.6)) < 1e-9, w
    # запрос "alpha gamma": d1 = 2*log(8/3) = 1.96 > d3 = 3*log(1.6) = 1.41 > d2
    s = {did: sum(v.get(t, 0.0) for t in _tokenize("alpha gamma", RE_TOK)) for did, v in w.items()}
    assert s["d1"] > s["d3"] > s["d2"], s
    print("FORMULA GUARD: exact TF*IDF 3/3 PASS", flush=True)


def segment(body: str):
    step = max(len(body) // 3, 1)
    out = []
    for i in range(3):
        seg = body[i * step:(i + 1) * step]
        if len(seg) >= 30:
            out.append(seg)
    return out


def module_doc(body: str) -> str:
    m = re.match(r'\s*"""(.*?)"""', body, re.S) or \
        re.match(r"\s*'''(.*?)'''", body, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1))[:500]


def augment(relpath: str, body: str) -> str:
    names = DEF_RE.findall(body)
    seen, ordered = set(), []
    for _, name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return (f"FILE: {relpath}\nSYMBOLS: {' '.join(ordered)}\n"
            f"DOC: {module_doc(body)}\n")


def build_index(texts):
    """texts: list[(doc_id, text)] -> (weights, ids). Копия bm25.py."""
    if not texts:
        print("FATAL: empty corpus", file=sys.stderr)
        sys.exit(2)
    tf_all, dfreq, ids = {}, {}, []
    for did, t in texts:
        ids.append(did)
        tf_all[did] = {}
        for tok in _tokenize(t, RE_TOK):
            tf_all[did][tok] = tf_all[did].get(tok, 0) + 1
        for tok in tf_all[did]:
            dfreq[tok] = dfreq.get(tok, 0) + 1
    N = len(texts)
    w = {}
    for did in ids:
        w[did] = {t: c * math.log((N - dfreq[t] + 0.5) / (dfreq[t] + 0.5) + 1)
                  for t, c in tf_all[did].items()}
    return w, ids


def search(w, ids, query, limit=81):
    qt = _tokenize(query, RE_TOK)
    scores = {did: sum(w[did].get(t, 0.0) for t in qt) for did in ids}
    ranked = sorted(ids, key=lambda d: scores[d], reverse=True)
    return [(d, scores[d]) for d in ranked if scores[d] > 0][:limit]


def score_file_chunk(ranked_files, file_ids_of_rank, queries):
    """ranked: list[(chunk_id)] per query; file-level dedup (как bench_e18._score)."""
    out = {k: [] for k in ("h1f", "h5f", "mrrf", "h1c", "h5c", "mrrc")}
    for (order, exp) in zip(ranked_files, queries):
        exp = exp.replace("\\", "/")
        seen, rank_f = set(), None
        for rk, f in enumerate(order):
            if f in seen:
                continue
            seen.add(f)
            if f == exp:
                rank_f = rk + 1
                break
        ranks_c = [i + 1 for i, f in enumerate(order) if f == exp]
        rank_c = min(ranks_c) if ranks_c else 10 ** 6
        out["h1f"].append(1 if rank_f == 1 else 0)
        out["h5f"].append(1 if rank_f and rank_f <= 5 else 0)
        out["mrrf"].append(1.0 / rank_f if rank_f else 0.0)
        out["h1c"].append(1 if rank_c == 1 else 0)
        out["h5c"].append(1 if rank_c <= 5 else 0)
        out["mrrc"].append(1.0 / rank_c)
    return {k: [v, float(sum(v) / len(v))] for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    guard_formula()

    rows = json.loads("[" + ",".join(
        l for l in FROZEN_Q.read_text(encoding="utf-8").splitlines() if l.strip()) + "]")
    scored = [q for q in rows if q["type"] in ("gold", "positive")]
    if not scored:
        print("FATAL: no queries", file=sys.stderr)
        sys.exit(2)

    files = sorted(set(GOLD_FILES) | set(DISTRACTORS))
    raw_texts, aug_texts, chunk_files = [], [], []
    for f in files:
        p = ROOT / f
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        rel = f.replace("\\", "/")
        for i, seg in enumerate(segment(body)):
            cid = f"{rel}#{i}"
            chunk_files.append((cid, rel))
            raw_texts.append((cid, seg))
            aug_texts.append((cid, augment(rel, body) + seg))
    if not raw_texts:
        print("FATAL: empty corpus", file=sys.stderr)
        sys.exit(2)

    res = {"n_chunks": len(raw_texts), "n_queries": len(scored)}
    for key, texts in (("raw", raw_texts), ("aug", aug_texts)):
        w, ids = build_index(texts)
        id2file = dict(chunk_files)
        ranked, exps = [], []
        for q in scored:
            hits = search(w, ids, q["query"])
            ranked.append([id2file[cid] for cid, _ in hits])
            exps.append(q["expect"])
        s = score_file_chunk(ranked, None, exps)
        res[key] = {"hit@1_file": s["h1f"][1], "hit@5_file": s["h5f"][1],
                    "mrr_file": s["mrrf"][1], "hit@1_chunk": s["h1c"][1],
                    "per_query_h1f": s["h1f"][0]}
        print(f"[{key}] n={len(texts)} h1f={s['h1f'][1]:.3f} h5f={s['h5f'][1]:.3f} "
              f"mrrf={s['mrrf'][1]:.3f}", flush=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK -> {out}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
