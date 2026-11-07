"""E49: hybrid code (BM25 seeds -> PageRank) + fixed docs reserve."""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\Project\MSCodeBase")
FROZEN = ROOT / "experiments" / "e49_hybrid_reserve" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e49_hybrid_reserve" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "experiments" / "e47_pagerank_docs"))
import run_pagerank_docs as e47  # noqa: E402

from src.core.search.synonyms_ru import RU_EN  # noqa: E402


def expand(tokens):
    out = list(tokens)
    for tok in tokens:
        for syn in RU_EN.get(tok.lower(), []):
            if syn not in out:
                out.append(syn)
    return out


def main():
    qs = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    nodes, file_nodes, out_edges_code, in_degree = e47.load_graph()
    code_files = sorted({n["file_path"] for n in nodes.values() if n["file_path"]})
    store, doc_texts, doc_previews = e47.load_docs()
    doc_files = sorted(doc_texts)
    code_set, doc_set = set(code_files), set(doc_files)
    print(f"code={len(code_files)} docs={len(doc_files)}")

    tidx = e47.token_file_index(nodes)
    doc_tidx = defaultdict(set)
    for fp, body in doc_texts.items():
        for part in e47.re.split(r"[^A-Za-zА-Яа-я0-9]+", fp + " " + body):
            low = part.lower()
            if len(low) >= 3:
                doc_tidx[low].add(fp)

    budgets = (1000, 2000, 4000)
    uniform_code = {f: 1.0 / len(code_files) for f in code_files}

    def make_pers(tokens, files, bm25_files=()):
        n = len(files)
        pers = {f: 1.0 / n for f in files}
        for tok in tokens:
            low = tok.lower()
            for f in tidx.get(low, ()):
                pers[f] = pers.get(f, 0.0) + (50.0 if any(ch.isupper() for ch in tok) or "_" in tok else 10.0)
            for f in doc_tidx.get(low, ()):
                pers[f] = pers.get(f, 0.0) + 10.0
        for f in files:
            fl = f.lower()
            for tok in tokens:
                if tok.lower() in fl:
                    pers[f] = pers.get(f, 0.0) + 10.0
        for f in bm25_files:
            if f in pers:
                pers[f] += 100.0
        return pers

    def dedup(order):
        out, seen = [], set()
        for f in order:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def docs_order(query, tokens):
        order, seen = [], set()
        for r in store.search(query, limit=100):
            fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            if fp in doc_set and fp not in seen:
                seen.add(fp)
                order.append(fp)
        scored = []
        for f in doc_files:
            if f in seen:
                continue
            body = doc_texts.get(f, "").lower()
            scored.append((sum(1 for tok in tokens if tok.lower() in body), f))
        scored.sort(key=lambda x: (-x[0], x[1]))
        order.extend(f for score, f in scored if score > 0)
        order.extend(f for score, f in scored if score == 0)
        return order

    def code_bm25_order(query):
        order, seen = [], set()
        for r in store.search(query, limit=100):
            fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            if fp in code_set and fp not in seen:
                seen.add(fp)
                order.append(fp)
        return order

    def map_text(order, budget):
        return e47.build_map(order, nodes, file_nodes, in_degree, doc_previews, budget)[0]

    def reserve_hit(code_order, doc_order, budget, ratio, gold):
        c = int(budget * ratio)
        d = budget - c
        return int(gold in (map_text(code_order, c) + "\n" + map_text(doc_order, d)))

    rows, lat = [], []
    for q in qs:
        t0 = time.perf_counter()
        toks = expand(e47.content_tokens(q["query"]))
        bm25_code = code_bm25_order(q["query"])
        bm_docs = docs_order(q["query"], toks)

        pers = make_pers(toks, code_files, bm25_code)
        pr = e47.pagerank(code_files, out_edges_code, pers)
        hybrid_code = sorted(code_files, key=lambda f: -pr.get(f, 0.0))
        bm25_code_full = dedup(bm25_code + hybrid_code)
        hybrid_full = dedup(hybrid_code + bm25_code)

        docs2 = dedup(bm_docs[:2] + hybrid_full)
        oracle = dedup(bm_docs + hybrid_full) if q["gold_file"] in doc_set else hybrid_full

        row = {"id": q["id"], "gold": q["gold_file"]}
        for b in budgets:
            row[f"base_{b}"] = int(q["gold_file"] in map_text(hybrid_full, b))
            row[f"bm25_code_{b}"] = int(q["gold_file"] in map_text(bm25_code_full, b))
            row[f"hybrid_code_{b}"] = int(q["gold_file"] in map_text(hybrid_full, b))
            row[f"reserve15_{b}"] = reserve_hit(hybrid_full, bm_docs, b, 0.85, q["gold_file"])
            row[f"reserve25_{b}"] = reserve_hit(hybrid_full, bm_docs, b, 0.75, q["gold_file"])
            row[f"docs2_code_{b}"] = int(q["gold_file"] in map_text(docs2, b))
            row[f"oracle_{b}"] = int(q["gold_file"] in map_text(oracle, b))
        lat.append((time.perf_counter() - t0) * 1000)
        rows.append(row)

    lat.sort()
    arms = ("base", "bm25_code", "hybrid_code", "reserve15", "reserve25", "docs2_code", "oracle")
    summary = {}
    for arm in arms:
        for b in budgets:
            summary[f"{arm}_{b}"] = sum(r[f"{arm}_{b}"] for r in rows) / len(rows)
    out = {
        "n": len(rows),
        "summary": summary,
        "p50_ms": statistics.median(lat),
        "p95_ms": lat[int(len(lat) * 0.95) - 1],
        "rows": rows,
    }
    (RESULTS / "e49.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for k, v in summary.items():
        print(f"{k:<18} {v:.3f}")
    print(f"p50={out['p50_ms']:.0f}ms p95={out['p95_ms']:.0f}ms")

    for subset, pred in (
        ("code", lambda r: not r["gold"].startswith("docs/")),
        ("docs", lambda r: r["gold"].startswith("docs/")),
    ):
        sel = [r for r in rows if pred(r)]
        print(f"[{subset}] n={len(sel)}")
        for arm in arms:
            print(" ", arm, [round(sum(r[f"{arm}_{b}"] for r in sel) / len(sel), 3) for b in budgets])


if __name__ == "__main__":
    raise SystemExit(main())
