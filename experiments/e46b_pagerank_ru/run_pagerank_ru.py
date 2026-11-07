"""E46: Aider-style file graph + personalized PageRank context map."""

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

from src.core.search.synonyms_ru import RU_EN

ROOT = Path(r"D:\Project\MSCodeBase")
FROZEN = ROOT / "experiments" / "e46b_pagerank_ru" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e46b_pagerank_ru" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
GRAPH = ROOT / "experiments" / "e46_pagerank_map" / "results" / "graph_complete.db"
if not GRAPH.exists():
    GRAPH = Path(
        r"C:\Users\misha\AppData\Local\Temp\opencode\mscodebase_symbolfix_backup_20261025_002249\graph.db"
    )

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
        nodes[r["id"]] = {
            "name": r["name"],
            "label": r["label"],
            "qualified_name": r["qualified_name"],
            "file_path": str(r["file_path"] or "").replace("\\", "/"),
            "properties": r["properties"],
        }
        if nodes[r["id"]]["file_path"]:
            file_nodes[nodes[r["id"]]["file_path"]].append(r["id"])

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
    in_edges = defaultdict(dict)
    for (sf, tf), w in edge_counts.items():
        out_edges[sf][tf] = out_edges[sf].get(tf, 0.0) + w
        in_edges[tf][sf] = in_edges[tf].get(sf, 0.0) + w
    return nodes, file_nodes, dict(out_edges), dict(in_edges), dict(in_degree)


def token_file_index(nodes):
    idx = defaultdict(set)
    for nid, n in nodes.items():
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


def build_map(ranked_files, nodes, file_nodes, in_degree, budget_tokens, max_symbols_per_file=8):
    lines = []
    used = 0
    budget_chars = budget_tokens * 4
    for f in ranked_files:
        if used >= budget_chars:
            break
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


def hit_map(ranked_files, gold, budget_tokens, nodes, file_nodes, in_degree):
    text, _ = build_map(
        ranked_files, nodes, file_nodes, in_degree, budget_tokens
    )
    return gold in text or text.count(gold) > 0


def main():
    qs = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    nodes, file_nodes, out_edges, in_edges, in_degree = load_graph()
    files = sorted({n["file_path"] for n in nodes.values() if n["file_path"]})
    print(f"files={len(files)} nodes={len(nodes)}")
    tidx = token_file_index(nodes)
    budgets = (1000, 2000, 4000)
    arms = {
        "degree": sorted(files, key=lambda f: (-in_degree.get(f, 0.0), f)),
        "global": None,
        "personalized": None,
    }
    uniform = {f: 1.0 / len(files) for f in files}
    arms["global"] = pagerank(files, out_edges, uniform)

    rows = []
    lat = []
    for q in qs:
        t0 = time.perf_counter()
        toks = content_tokens(q["query"])
        en_toks = list(toks)
        for tok in toks:
            for syn in RU_EN.get(tok.lower(), []):
                if syn not in en_toks:
                    en_toks.append(syn)
        pers = dict(uniform)
        for tok in en_toks:
            low = tok.lower()
            for f in tidx.get(low, set()):
                pers[f] = pers.get(f, 0.0) + (50.0 if any(ch.isupper() for ch in tok) or "_" in tok else 10.0)
        # exact path/symbol substring boosts
        for f in files:
            fl = f.lower()
            for tok in en_toks:
                if tok.lower() in fl:
                    pers[f] = pers.get(f, 0.0) + 10.0
        pr = pagerank(files, out_edges, pers)
        ranked = {
            "degree": arms["degree"],
            "global": sorted(files, key=lambda f: -arms["global"].get(f, 0.0)),
            "personalized": sorted(files, key=lambda f: -pr.get(f, 0.0)),
        }
        row = {"id": q["id"], "gold": q["gold_file"]}
        for arm, order in ranked.items():
            for b in budgets:
                row[f"{arm}_{b}"] = int(
                    hit_map(order, q["gold_file"], b, nodes, file_nodes, in_degree)
                )
        lat.append((time.perf_counter() - t0) * 1000)
        rows.append(row)

    lat.sort()
    summary = {}
    for arm in ranked:
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
    (RESULTS / "e46.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for k, v in summary.items():
        print(f"{k:<18} {v:.3f}")
    print(f"p50={out['p50_ms']:.0f}ms p95={out['p95_ms']:.0f}ms")


if __name__ == "__main__":
    raise SystemExit(main())




