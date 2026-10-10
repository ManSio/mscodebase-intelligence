#!/usr/bin/env python3
# -*- coding: utf-8
"""E25-B: on-demand cosine-rerank кандидатов плеча A.
Транспорт — копия bench_e18 (POST /v1/embeddings, /tokenize-trim 400 tok, L2+cosine).
Плечи: raw (как есть), coderet (префиксы вендора E18), e5 (прод :8080, контроль).
T10: 0 запросов -> exit(2); 0 кандидатов на запрос = готовый промах (embed пропускаем).
USAGE: python experiments/e25_ondemand/e25_rerank.py --cands <json> --out <json> [--port 8110]
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import argparse
import json
import time
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "experiments" / "embeddinggemma2_eval"))
from bench_e18 import Server, E18MODELS  # noqa: E402 (тот же Server/пути, без дрейфа)

Q4 = E18MODELS / "embeddinggemma-2-UD-Q4_K_XL.gguf"
E5_URL = "http://127.0.0.1:8080"


def q_raw(q):
    return q


def d_raw(t, title):
    return t


def q_coderet(q):
    return f"task: code retrieval | query: {q}"


def d_coderet(t, title):
    return f"title: {title} | text: {t}"


class T:
    def __init__(self, base):
        self.c = httpx.Client(base_url=base, timeout=240.0)

    def ntok(self, text):
        r = self.c.post("/tokenize", json={"content": text, "add_special": False}, timeout=30)
        r.raise_for_status()
        return len(r.json()["tokens"])

    def prep(self, text, target=400):
        t, n = text, self.ntok(text)
        for _ in range(6):
            if n <= target:
                return t
            t = t[: int(len(t) * (target / n) * 0.95) or 1]
            n = self.ntok(t)
        return t

    def embed(self, texts):
        s = time.perf_counter()
        r = self.c.post("/v1/embeddings", json={"input": list(texts)})
        dt = (time.perf_counter() - s) * 1000
        if r.status_code != 200:
            raise RuntimeError(f"embed HTTP {r.status_code}: {r.text[:200]}")
        items = sorted(r.json()["data"], key=lambda x: x.get("index", 0))
        return np.asarray([d["embedding"] for d in items], dtype=np.float32), dt


def rerank(t, qfn, dfn, query, cands):
    if not cands:
        return {"rank": None, "ms": 0.0}
    texts = [qfn(query)] + [dfn(t.prep(c["text"]), c["file"]) for c in cands]
    V, dt = t.embed(texts)
    Vn = V / np.linalg.norm(V, axis=1, keepdims=True)
    sim = Vn[0] @ Vn[1:].T
    order = np.argsort(-sim)
    files = [c["file"].replace("\\", "/") for c in cands]
    return {"rank": None, "ms": dt,
            "_sim": [float(sim[i]) for i in order], "_files": [files[i] for i in order]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cands", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=8110)
    ap.add_argument("--no-q4", action="store_true", help="только e5 (когда b11476 не нужен)")
    args = ap.parse_args()
    data = json.loads(Path(args.cands).read_text(encoding="utf-8"))
    queries = data["queries"]
    if not queries:
        print("FATAL: empty queries", file=sys.stderr)
        sys.exit(2)
    res = {"queries": []}
    srv = None
    try:
        if not args.no_q4:
            if not Q4.exists():
                print(f"FATAL: missing {Q4}", file=sys.stderr)
                sys.exit(2)
            srv = Server(Q4, args.port, E18MODELS / "e25_q4_stderr.log", 512, 2048)
            srv.start()
            tq4 = T(f"http://127.0.0.1:{args.port}")
        te5 = T(E5_URL)
        for item in queries:
            q, exp, cands = item["q"], item["exp"].replace("\\", "/"), item["candidates"]
            row = {"q": q, "exp": exp, "n_cand": len(cands), "arms": {}}
            for name, t, qf, df in (("raw", tq4, q_raw, d_raw),
                                     ("coderet", tq4, q_coderet, d_coderet),
                                     ("e5", te5, q_raw, d_raw)) if not args.no_q4 else (("e5", te5, q_raw, d_raw),):
                try:
                    r = rerank(t, qf, df, q, cands)
                    rank = None
                    if r["rank"] is None and "_files" in r:
                        for i, f in enumerate(r["_files"]):
                            if f == exp or f.endswith(exp):
                                rank = i + 1
                                break
                    row["arms"][name] = {"rank": rank, "ms": round(r["ms"], 1)}
                except Exception as e:
                    row["arms"][name] = {"rank": None, "ms": -1,
                                         "err": f"{type(e).__name__}"}
                print(f"[{name}] rank={row['arms'][name]['rank']} "
                      f"ms={row['arms'][name]['ms']} :: {q[:45]}", flush=True)
            res["queries"].append(row)
    finally:
        if srv:
            srv.stop()
    p = Path(args.out)
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK -> {p}")


if __name__ == "__main__":
    main()
