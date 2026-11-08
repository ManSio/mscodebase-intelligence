"""E50: BM25 score-margin router between docs and code channels."""

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
FROZEN = ROOT / "experiments" / "e50_score_route" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e50_score_route" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "experiments" / "e47_pagerank_docs"))
import run_pagerank_docs as e47  # noqa: E402

from src.core.search.synonyms_ru import RU_EN  # noqa: E402

THRESHOLDS = (0.8, 1.0, 1.2, 1.5, 2.0)


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
    nodes, file_nodes, out_edges, in_degree = e47.load_graph()
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

    def make_pers(tokens):
        n = len(code_files)
        pers = {f: 1.0 / n for f in code_files}
        for tok in tokens:
            low = tok.lower()
            for f in tidx.get(low, ()):
                pers[f] = pers.get(f, 0.0) + (50.0 if any(ch.isupper() for ch in tok) or "_" in tok else 10.0)
        for f in code_files:
            fl = f.lower()
            for tok in tokens:
                if tok.lower() in fl:
                    pers[f] = pers.get(f, 0.0) + 10.0
        return pers

    def dedup(order):
        out, seen = [], set()
        for f in order:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def docs_bm25(query, tokens):
        order, seen = [], set()
        for r in store.search(query, limit=1000):
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
        order.extend(f for s, f in scored if s > 0)
        order.extend(f for s, f in scored if s == 0)
        return order

    def map_text(order, budget):
        return e47.build_map(order, nodes, file_nodes, in_degree, doc_previews, budget)[0]

    budgets = (1000, 2000, 4000)
    rows, lat = [], []
    for q in qs:
        t0 = time.perf_counter()
        toks = expand(e47.content_tokens(q["query"]))
        results = store.search(q["query"], limit=1000)

        doc_rel = 0.0
        code_rel = 0.0
        doc_hits, code_hits = [], []
        for r in results:
            fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            rel = float(r.get("final_score") or 0.0)
            if fp in doc_set:
                doc_rel = max(doc_rel, rel)
                doc_hits.append(fp)
            elif fp in code_set:
                code_rel = max(code_rel, rel)
                code_hits.append(fp)

        doc_order = docs_bm25(q["query"], toks)
        pers = make_pers(toks)
        pr = e47.pagerank(code_files, out_edges, pers)
        code_order = sorted(code_files, key=lambda f: -pr.get(f, 0.0))
        # BM25 code hits first, then PageRank
        code_order = dedup(code_hits + code_order)

        gold = q["gold_file"]
        row = {"id": q["id"], "gold": gold, "doc_rel": doc_rel, "code_rel": code_rel}
        for b in budgets:
            row[f"base_{b}"] = int(gold in map_text(code_order, b))
            row[f"docs_{b}"] = int(gold in map_text(doc_order, b))
            row[f"oracle_{b}"] = int(gold in map_text(doc_order + code_order if gold in doc_set else code_order, b))
        for t in THRESHOLDS:
            route_docs = doc_rel > t * code_rel if code_rel > 0 else doc_rel > 0
            order = dedup(doc_order + code_order) if route_docs else dedup(code_order + doc_order)
            row[f"route{t}_docs"] = int(route_docs)
            for b in budgets:
                row[f"route{t}_{b}"] = int(gold in map_text(order, b))
        lat.append((time.perf_counter() - t0) * 1000)
        rows.append(row)

    lat.sort()
    arms = ["base", "docs", "oracle"] + [f"route{t}" for t in THRESHOLDS]
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
    (RESULTS / "e50.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("docs queries routed (of 8):")
    for t in THRESHOLDS:
        n = sum(1 for r in rows if r["gold"].startswith("docs/") and r[f"route{t}_docs"])
        print(f"  t={t}: {n}/8")
    for k, v in summary.items():
        print(f"{k:<16} {v:.3f}")
    print(f"p50={out['p50_ms']:.0f}ms p95={out['p95_ms']:.0f}ms")

    for subset, pred in (
        ("code", lambda r: not r["gold"].startswith("docs/")),
        ("docs", lambda r: r["gold"].startswith("docs/")),
    ):
        sel = [r for r in rows if pred(r)]
        print(f"[{subset}] n={len(sel)}")
        for arm in arms:
            print(" ", arm, [round(sum(r[f"{arm}_{b}"] for r in sel) / len(sel), 3) for b in budgets])

    # held-out: choose threshold on odd IDs (1k), evaluate even IDs (1k)
    odd = rows[::2]
    even = rows[1::2]
    best_t, best_v = None, -1.0
    for t in THRESHOLDS:
        v = sum(r[f"route{t}_1000"] for r in odd) / len(odd)
        if v > best_v:
            best_t, best_v = t, v
    held = sum(r[f"route{best_t}_1000"] for r in even) / len(even)
    full = summary[f"route{best_t}_1000"]
    print(f"held-out: odd best t={best_t} odd={best_v:.3f} even={held:.3f} full={full:.3f}")


if __name__ == "__main__":
    raise SystemExit(main())

