"""E51: deterministic 4-step agentic retrieval loop over SQLite FTS5 + graph."""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\Project\MSCodeBase")
FROZEN = ROOT / "experiments" / "e51b_agentic_clean" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e51b_agentic_clean" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "experiments" / "e47_pagerank_docs"))
import run_pagerank_docs as e47  # noqa: E402

from src.core.search.synonyms_ru import RU_EN  # noqa: E402

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
STOP_IDENTS = {
    "self", "true", "false", "none", "return", "import", "from", "class",
    "def", "async", "await", "with", "for", "while", "else", "elif", "try",
    "except", "raise", "yield", "lambda", "pass", "break", "continue", "and",
    "not", "the", "this", "that", "with", "file", "path", "data", "text",
}


def expand_query(q: str):
    toks = e47.content_tokens(q)
    out = list(toks)
    for tok in toks:
        for syn in RU_EN.get(tok.lower(), []):
            if syn not in out:
                out.append(syn)
    return out


def add_rrf(scores: dict, results, weight=1.0):
    seen = set()
    rank = 0
    for r in results:
        fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
        if not fp or fp in seen:
            continue
        seen.add(fp)
        scores[fp] = scores.get(fp, 0.0) + weight / (60.0 + rank)
        rank += 1


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
    print(f"code={len(code_files)} docs={len(doc_files)}")

    def valid(fp: str) -> bool:
        return not fp.startswith("experiments/") and not fp.startswith(".mscodebase/")

    def search(query: str, limit: int = 500):
        return [
            r for r in store.search(query, limit=limit)
            if valid(str((r.get("metadata") or {}).get("file") or "").replace("\\", "/"))
        ]

    neighbors = defaultdict(set)
    for sf, targets in out_edges.items():
        for tf in targets:
            if sf != tf:
                neighbors[sf].add(tf)
                neighbors[tf].add(sf)

    def best_by_file(results):
        best = {}
        for r in results:
            fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            if not fp:
                continue
            score = float(r.get("final_score") or 0.0)
            if fp not in best or score > best[fp][0]:
                best[fp] = (score, r)
        return best

    def ranked_files(results):
        best = best_by_file(results)
        return [
            f for f, _ in sorted(best.items(), key=lambda kv: -kv[1][0])
        ]

    def read_text(fp, results):
        best = best_by_file(results)
        if fp not in best:
            return ""
        text = best[fp][1].get("text") or ""
        return text[:2000]

    rows, lat, tool_calls, token_counts = [], [], [], []
    for q in qs:
        t0 = time.perf_counter()
        calls = 0
        tokens = 0
        scores = defaultdict(float)
        expanded = expand_query(q["query"])

        # Step 1: original query
        res1 = search(q["query"], limit=500)
        calls += 1
        add_rrf(scores, res1, 1.0)
        top1 = ranked_files(res1)[:5]

        # Step 2: read top-3 and extract identifiers
        id_counts = defaultdict(int)
        for fp in top1[:3]:
            text = read_text(fp, res1)
            tokens += len(text) // 4
            for ident in IDENT_RE.findall(text):
                low = ident.lower()
                if low in STOP_IDENTS or len(low) < 4:
                    continue
                if any(low == t.lower() for t in expanded):
                    continue
                id_counts[ident] += 1
        top_idents = [i for i, _ in sorted(id_counts.items(), key=lambda kv: -kv[1])[:3]]

        # Step 3: expanded query
        if top_idents:
            q2 = q["query"] + " " + " ".join(top_idents)
            res2 = search(q2, limit=500)
            calls += 1
            add_rrf(scores, res2, 0.8)
        else:
            res2 = []

        # Step 4: graph neighbours of top files
        top_now = sorted(scores.items(), key=lambda kv: -kv[1])[:5]
        for fp, sc in top_now:
            for nb in list(neighbors.get(fp, ()))[:20]:
                scores[nb] = scores.get(nb, 0.0) + 0.15 / (60.0 + scores[fp])
                calls += 0  # graph lookup is local, not a tool call

        # Final ranking: RRF + symbol overlap + graph proximity
        def final_score(fp):
            base = scores.get(fp, 0.0)
            names = " ".join(nodes[nid]["name"] for nid in file_nodes.get(fp, []))
            hay = (fp + " " + names).lower()
            overlap = sum(1 for t in expanded if t.lower() in hay)
            return base + 0.01 * overlap

        order = sorted(scores, key=lambda f: -final_score(f))
        top5 = order[:5]

        # Baseline: single BM25
        base_order = ranked_files(res1)
        row = {
            "id": q["id"],
            "gold": q["gold_file"],
            "agent_top1": top5[0] if top5 else "",
            "agent_top5": top5,
            "single_top1": base_order[0] if base_order else "",
            "single_top5": base_order[:5],
            "tool_calls": calls,
            "tokens": tokens,
            "idents": top_idents,
        }
        rows.append(row)
        lat.append((time.perf_counter() - t0) * 1000)
        tool_calls.append(calls)
        token_counts.append(tokens)

    lat.sort()
    summary = {}
    for arm in ("agent", "single"):
        summary[f"{arm}_hit@1"] = sum(r[f"{arm}_top1"] == r["gold"] for r in rows) / len(rows)
        summary[f"{arm}_hit@5"] = sum(r["gold"] in r[f"{arm}_top5"] for r in rows) / len(rows)
    out = {
        "n": len(rows),
        "summary": summary,
        "p50_ms": statistics.median(lat),
        "p95_ms": lat[int(len(lat) * 0.95) - 1],
        "avg_tool_calls": sum(tool_calls) / len(tool_calls),
        "avg_tokens": sum(token_counts) / len(token_counts),
        "rows": rows,
    }
    (RESULTS / "e51b.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for k, v in summary.items():
        print(f"{k:<18} {v:.3f}")
    print(
        f"p50={out['p50_ms']:.0f}ms p95={out['p95_ms']:.0f}ms "
        f"calls={out['avg_tool_calls']:.2f} tokens={out['avg_tokens']:.0f}"
    )

    for subset, pred in (
        ("code", lambda r: not r["gold"].startswith("docs/")),
        ("docs", lambda r: r["gold"].startswith("docs/")),
    ):
        sel = [r for r in rows if pred(r)]
        print(f"[{subset}] n={len(sel)}")
        for arm in ("agent", "single"):
            h1 = sum(r[f"{arm}_top1"] == r["gold"] for r in sel) / len(sel)
            h5 = sum(r["gold"] in r[f"{arm}_top5"] for r in sel) / len(sel)
            print(f"  {arm}: hit@1={h1:.3f} hit@5={h5:.3f}")


if __name__ == "__main__":
    raise SystemExit(main())

