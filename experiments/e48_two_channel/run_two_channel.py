"""E48: two-channel repo map — code PageRank + docs BM25, merged outside."""

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
FROZEN = ROOT / "experiments" / "e48_two_channel" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e48_two_channel" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "experiments" / "e47_pagerank_docs"))
import run_pagerank_docs as e47  # noqa: E402

from src.core.search.synonyms_ru import RU_EN  # noqa: E402

DOC_HINTS = (
    "docs", "readme", "докум", "архитектур", "architecture", "design",
    "benchmark", "roadmap", "audit", "report", "guide", "инструкц",
    "план", "spec", "adr",
)


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
    doc_set = set(doc_files)
    all_files = sorted(set(code_files) | doc_set)
    print(f"code_files={len(code_files)} docs={len(doc_files)} all={len(all_files)}")

    tidx = e47.token_file_index(nodes)
    doc_tidx = defaultdict(set)
    for fp, body in doc_texts.items():
        for part in e47.re.split(r"[^A-Za-zА-Яа-я0-9]+", fp + " " + body):
            low = part.lower()
            if len(low) >= 3:
                doc_tidx[low].add(fp)

    budgets = (1000, 2000, 4000)
    uniform_code = {f: 1.0 / len(code_files) for f in code_files}
    uniform_all = {f: 1.0 / len(all_files) for f in all_files}

    def make_pers(tokens, files):
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
        return pers

    def docs_bm25_order(query, tokens):
        order = []
        seen = set()
        for r in store.search(query, limit=50):
            fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            if fp in doc_set and fp not in seen:
                seen.add(fp)
                order.append(fp)
        scored = []
        for f in doc_files:
            if f in seen:
                continue
            body = doc_texts.get(f, "").lower()
            score = sum(1 for tok in tokens if tok.lower() in body)
            scored.append((score, f))
        scored.sort(key=lambda x: (-x[0], x[1]))
        order.extend(f for score, f in scored if score > 0)
        order.extend(f for score, f in scored if score == 0)
        return order

    def merged_order(first, second):
        out = []
        seen = set()
        for f in first + second:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def interleave(a, b):
        out = []
        seen = set()
        i = j = 0
        while i < len(a) or j < len(b):
            if i < len(a):
                if a[i] not in seen:
                    seen.add(a[i])
                    out.append(a[i])
                i += 1
            if j < len(b):
                if b[j] not in seen:
                    seen.add(b[j])
                    out.append(b[j])
                j += 1
        return out

    def map_text(order, budget):
        return e47.build_map(
            order, nodes, file_nodes, in_degree, doc_previews, budget
        )[0]

    def split_hit(code_order, doc_order, budget, ratio, gold):
        c = int(budget * ratio)
        d = budget - c
        text = map_text(code_order, c) + "\n" + map_text(doc_order, d)
        return int(gold in text)

    rows = []
    lat = []
    for q in qs:
        t0 = time.perf_counter()
        toks = expand(e47.content_tokens(q["query"]))
        pers_code = make_pers(toks, code_files)
        pr_code = e47.pagerank(code_files, out_edges_code, pers_code)
        code_order = sorted(code_files, key=lambda f: -pr_code.get(f, 0.0))
        doc_order = docs_bm25_order(q["query"], toks)
        gold = q["gold_file"]
        is_docs = any(h in q["query"].lower() for h in DOC_HINTS)

        route_order = merged_order(doc_order, code_order) if is_docs else merged_order(code_order, doc_order)
        oracle_order = merged_order(doc_order, code_order) if gold in doc_set else merged_order(code_order, doc_order)
        merged = interleave(code_order, doc_order)

        row = {"id": q["id"], "gold": gold, "is_docs": is_docs}
        for b in budgets:
            row[f"base_{b}"] = int(gold in map_text(code_order, b))
            row[f"bm25_docs_{b}"] = int(gold in map_text(doc_order, b))
            row[f"route_{b}"] = int(gold in map_text(route_order, b))
            row[f"interleave_{b}"] = int(gold in map_text(merged, b))
            row[f"oracle_{b}"] = int(gold in map_text(oracle_order, b))
            row[f"split75_{b}"] = split_hit(code_order, doc_order, b, 0.75, gold)
            row[f"split50_{b}"] = split_hit(code_order, doc_order, b, 0.50, gold)
        lat.append((time.perf_counter() - t0) * 1000)
        rows.append(row)

    lat.sort()
    arms = ("base", "bm25_docs", "route", "interleave", "split75", "split50", "oracle")
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
    (RESULTS / "e48.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for k, v in summary.items():
        print(f"{k:<18} {v:.3f}")
    print(f"p50={out['p50_ms']:.0f}ms p95={out['p95_ms']:.0f}ms")

    for subset, pred in (
        ("code", lambda r: not r["is_docs"]),
        ("docs", lambda r: r["is_docs"]),
    ):
        sel = [r for r in rows if pred(r)]
        print(f"[{subset}] n={len(sel)}")
        for arm in arms:
            print(" ", arm, [round(sum(r[f"{arm}_{b}"] for r in sel) / len(sel), 3) for b in budgets])


if __name__ == "__main__":
    raise SystemExit(main())
