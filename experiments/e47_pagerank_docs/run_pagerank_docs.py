"""E47: PageRank repo map with docs nodes + BM25 seed + RU->EN."""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

ROOT = Path(r"D:\Project\MSCodeBase")
FROZEN = ROOT / "experiments" / "e47_pagerank_docs" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e47_pagerank_docs" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
GRAPH = ROOT / "experiments" / "e46_pagerank_map" / "results" / "graph_complete.db"

from src.core.indexing.chunk_store import SQLiteChunkStore, get_chunks_db_path
from src.core.search.synonyms_ru import RU_EN

RU_STOP = set(
    """
    почему как что зачем насколько какой каким какая какие где когда это этот эта эти
    и а но или же ли бы то все всё если чтобы может можно нужно надо делает делают
    работает работают используется используются происходит происходят относится
    является были был была есть не ни в на с со по для из к ко о об от до при
    между через после перед под над без более менее самый самая самое
    чем чего чему кем том того этому этих также только уже еще ещё
    вот так там тут мы вы они он она оно
    """.split()
)

EDGE_TYPES = ("CALLS", "ASSIGNED_FROM", "IMPORTS", "DECORATES", "OVERRIDES")


def content_tokens(q: str):
    toks = re.findall(r"[\w\.:/-]+", q, flags=re.UNICODE)
    out = []
    for t in toks:
        low = t.lower().strip(".,!?;:()[]{}\"'«»")
        if low and low not in RU_STOP and len(low) >= 2:
            out.append(t)
    return out


def load_graph():
    conn = sqlite3.connect(str(GRAPH))
    conn.row_factory = sqlite3.Row
    nodes = {}
    file_nodes = defaultdict(list)
    for r in conn.execute(
        "SELECT id, name, label, qualified_name, file_path, properties FROM nodes"
    ):
        fp = str(r["file_path"] or "").replace("\\", "/")
        nodes[r["id"]] = {
            "name": r["name"],
            "label": r["label"],
            "qualified_name": r["qualified_name"],
            "file_path": fp,
            "properties": r["properties"],
        }
        if fp:
            file_nodes[fp].append(r["id"])

    edge_counts = defaultdict(int)
    in_degree = defaultdict(float)
    placeholders = ",".join("?" for _ in EDGE_TYPES)
    for r in conn.execute(
        f"SELECT source_id, target_id, type, weight FROM edges WHERE type IN ({placeholders})",
        EDGE_TYPES,
    ):
        s = nodes.get(r["source_id"])
        t = nodes.get(r["target_id"])
        if not s or not t:
            continue
        sf, tf = s["file_path"], t["file_path"]
        if not sf or not tf or sf == tf:
            continue
        edge_counts[(sf, tf)] += 1
        in_degree[tf] += float(r["weight"] or 1.0)
    conn.close()

    out_edges = defaultdict(dict)
    for (sf, tf), w in edge_counts.items():
        out_edges[sf][tf] = out_edges[sf].get(tf, 0.0) + w
    return nodes, dict(file_nodes), dict(out_edges), dict(in_degree)


def token_file_index(nodes):
    idx = defaultdict(set)
    for n in nodes.values():
        fp = n["file_path"]
        if not fp:
            continue
        for part in re.split(r"[^A-Za-zА-Яа-я0-9]+", fp + " " + n["name"]):
            low = part.lower()
            if len(low) >= 3:
                idx[low].add(fp)
    return idx


def pagerank(files, out_edges, personalization, damping=0.85, iters=30):
    n = len(files)
    idx = {f: i for i, f in enumerate(files)}
    pers = np.asarray([max(personalization.get(f, 1.0 / n), 0.0) for f in files])
    if pers.sum() <= 0:
        pers = np.ones(n)
    pers /= pers.sum()
    rank = pers.copy()
    out_w = np.zeros(n)
    for f in files:
        out_w[idx[f]] = sum(out_edges.get(f, {}).values())
    for _ in range(iters):
        incoming = np.zeros(n)
        for f in files:
            ow = out_w[idx[f]]
            if ow <= 0:
                continue
            base = damping * rank[idx[f]] / ow
            for tgt, w in out_edges.get(f, {}).items():
                ti = idx.get(tgt)
                if ti is not None:
                    incoming[ti] += base * w
        dangling = float(rank[out_w == 0].sum())
        rank = (1 - damping) * pers + incoming + damping * dangling * pers
    return {f: float(rank[idx[f]]) for f in files}


def build_map(ranked_files, nodes, file_nodes, in_degree, doc_previews, budget_tokens,
              max_symbols_per_file=8):
    lines = []
    used = 0
    budget_chars = budget_tokens * 4
    for f in ranked_files:
        if used >= budget_chars:
            break
        if f in doc_previews:
            line = f"{f}: {doc_previews[f]}"
            lines.append(line)
            used += len(line) + 1
            continue
        nids = sorted(
            file_nodes.get(f, []),
            key=lambda nid: (-in_degree.get(f, 0.0), nodes[nid]["name"]),
        )[:max_symbols_per_file]
        if not nids:
            continue
        lines.append(f"{f}:")
        used += len(f) + 2
        for nid in nids:
            n = nodes[nid]
            sig = ""
            try:
                props = json.loads(n["properties"] or "{}")
                sig = props.get("signature", "") or ""
            except Exception:
                sig = ""
            line = f"  {n['label']} {n['name']}{(' ' + sig) if sig else ''}"
            lines.append(line)
            used += len(line) + 1
            if used >= budget_chars:
                break
    return "\n".join(lines), used // 4


def hit_map(ranked_files, gold, budget_tokens, nodes, file_nodes, in_degree, doc_previews):
    text, _ = build_map(
        ranked_files, nodes, file_nodes, in_degree, doc_previews, budget_tokens
    )
    return gold in text


def load_docs():
    store = SQLiteChunkStore(get_chunks_db_path(ROOT))
    docs = {}
    for r in store.all_records():
        fp = str(r.get("file_path") or "").replace("\\", "/")
        if not fp:
            continue
        if fp.startswith("docs/") or fp.lower().endswith((".md", ".txt", ".rst")):
            docs.setdefault(fp, []).append(r)
    previews = {}
    texts = {}
    for fp, recs in docs.items():
        body = "\n".join((r.get("text_full") or r.get("text") or "") for r in recs)
        texts[fp] = body
        first = ""
        for line in body.splitlines():
            s = line.strip().strip("#").strip()
            if s:
                first = s
                break
        previews[fp] = first[:120]
    return store, texts, previews


def main():
    qs = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    nodes, file_nodes, out_edges_code, in_degree = load_graph()
    code_files = sorted({n["file_path"] for n in nodes.values() if n["file_path"]})
    store, doc_texts, doc_previews = load_docs()
    doc_files = sorted(doc_texts)
    all_files = sorted(set(code_files) | set(doc_files))
    print(f"code_files={len(code_files)} docs={len(doc_files)} all={len(all_files)} nodes={len(nodes)}")

    tidx = token_file_index(nodes)
    doc_tidx = defaultdict(set)
    for fp, body in doc_texts.items():
        for part in re.split(r"[^A-Za-zА-Яа-я0-9]+", fp + " " + body):
            low = part.lower()
            if len(low) >= 3:
                doc_tidx[low].add(fp)

    symbol_names = defaultdict(set)
    for n in nodes.values():
        if n["name"]:
            symbol_names[n["name"].lower()].add(n["file_path"])
    doc_edges = defaultdict(dict)
    ident_re = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
    for fp, body in doc_texts.items():
        targets = set()
        for ident in ident_re.findall(body):
            for tf in symbol_names.get(ident.lower(), ()):
                if tf and tf != fp:
                    targets.add(tf)
        for tf in targets:
            doc_edges[fp][tf] = doc_edges[fp].get(tf, 0.0) + 1.0

    out_edges_all = {f: dict(v) for f, v in out_edges_code.items()}
    for f, edges in doc_edges.items():
        out_edges_all.setdefault(f, {}).update(edges)

    def expand(tokens):
        out = list(tokens)
        for tok in tokens:
            for syn in RU_EN.get(tok.lower(), []):
                if syn not in out:
                    out.append(syn)
        return out

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
                pers[f] += 50.0
        return pers

    budgets = (1000, 2000, 4000)
    uniform_code = {f: 1.0 / len(code_files) for f in code_files}
    uniform_all = {f: 1.0 / len(all_files) for f in all_files}

    rows = []
    lat = []
    for q in qs:
        t0 = time.perf_counter()
        toks = expand(content_tokens(q["query"]))

        bm25 = store.search(q["query"], limit=20)
        bm25_files = []
        for r in bm25:
            fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            if fp and fp in uniform_all and fp not in bm25_files:
                bm25_files.append(fp)
        bm25_scores = []
        for r in bm25:
            fp = str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            if fp:
                bm25_scores.append((fp, float(r.get("final_score") or 0.0)))
        seen = set()
        bm25_order = []
        for fp, _ in sorted(bm25_scores, key=lambda x: -x[1]):
            if fp in uniform_all and fp not in seen:
                seen.add(fp)
                bm25_order.append(fp)
        bm25_order += [f for f in all_files if f not in seen]

        pers_code = make_pers(toks, code_files)
        pers_all = make_pers(toks, all_files)
        pers_bm25 = make_pers(toks, all_files, bm25_files)

        pr_code = pagerank(code_files, out_edges_code, pers_code)
        pr_docs = pagerank(all_files, out_edges_all, pers_all)
        pr_bm25 = pagerank(all_files, out_edges_all, pers_bm25)

        ranked = {
            "bm25": bm25_order,
            "base": sorted(code_files, key=lambda f: -pr_code.get(f, 0.0)),
            "docs": sorted(all_files, key=lambda f: -pr_docs.get(f, 0.0)),
            "docs_bm25": sorted(all_files, key=lambda f: -pr_bm25.get(f, 0.0)),
        }
        row = {"id": q["id"], "gold": q["gold_file"]}
        for arm, order in ranked.items():
            for b in budgets:
                row[f"{arm}_{b}"] = int(
                    hit_map(order, q["gold_file"], b, nodes, file_nodes, in_degree, doc_previews)
                )
        lat.append((time.perf_counter() - t0) * 1000)
        rows.append(row)

    lat.sort()
    summary = {}
    for arm in ("bm25", "base", "docs", "docs_bm25"):
        for b in budgets:
            key = f"{arm}_{b}"
            summary[key] = sum(r[key] for r in rows) / len(rows)
    out = {
        "n": len(rows),
        "summary": summary,
        "p50_ms": statistics.median(lat),
        "p95_ms": lat[int(len(lat) * 0.95) - 1],
        "rows": rows,
    }
    (RESULTS / "e47.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for k, v in summary.items():
        print(f"{k:<16} {v:.3f}")
    print(f"p50={out['p50_ms']:.0f}ms p95={out['p95_ms']:.0f}ms")


if __name__ == "__main__":
    raise SystemExit(main())
