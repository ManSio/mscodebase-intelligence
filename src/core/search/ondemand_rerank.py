"""On-demand cosine rerank (Phase 2 of the approved stack migration, E25).

Instead of scoring against STORED vectors, embed the query and the top-N
fused candidates LIVE at request time and sort by cosine. Measured E25:
recall@10 6/10 -> h1 5/10 (Q4, p50 2.2s) / h1 3/10 (e5, p50 0.6s) with ZERO
stored vectors. Nothing is written to the index by this module.

Pure functions (numpy only) — the engine supplies embeddings, tests inject
fake ones. Final scores are cosine similarities (higher = better), ties keep
fused order (stable sort). Candidates without text are dropped by the caller
(split_embed_inputs) and counted there.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

import numpy as np

__all__ = ["cosine_sims", "rerank_by_cosine", "split_embed_inputs"]


def cosine_sims(query_vec: Sequence[float], doc_vecs: Sequence[Sequence[float]]) -> List[float]:
    """L2-normalized cosine similarities of one query against docs."""
    q = np.asarray(query_vec, dtype=np.float32)
    d = np.asarray(list(doc_vecs), dtype=np.float32)
    qn = q / (np.linalg.norm(q) or 1.0)
    dn = d / (np.linalg.norm(d, axis=1, keepdims=True) + 1e-12)
    return [float(x) for x in (dn @ qn)]


def rerank_by_cosine(
    candidates: List[Dict[str, Any]],
    query_vec: Sequence[float],
    doc_vecs: Sequence[Sequence[float]],
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    """Re-sort usable candidates by live cosine (stable: ties keep fused order)."""
    sims = cosine_sims(query_vec, doc_vecs)
    scored: List[Dict[str, Any]] = []
    for cand, sim in zip(candidates, sims):
        item = dict(cand)
        item["final_score"] = sim
        meta = dict(item.get("metadata") or {})
        meta["rerank_mode"] = "ondemand_cosine"
        item["metadata"] = meta
        scored.append(item)
    scored.sort(key=lambda r: r["final_score"], reverse=True)
    return scored[: max(top_n, 0)]


def split_embed_inputs(
    query: str,
    candidates: List[Dict[str, Any]],
    max_chars: int = 1600,
) -> tuple[str, List[Dict[str, Any]], List[str], int]:
    """(query, usable_cands, [query_text] + [doc_texts], skipped_no_text).

    E25 protocol trimmed candidate texts to ~400 tokens before embedding
    (tokenize-trim). A char cap is a tokenizer-free approximation; it keeps
    on-demand rerank latency bounded on long chunks.
    """
    usable = [c for c in candidates if (c.get("text_full") or c.get("text") or "")]
    texts = []
    for c in usable:
        t = str(c.get("text_full") or c.get("text"))
        if max_chars and len(t) > max_chars:
            t = t[:max_chars]
        texts.append(t)
    return query, usable, [query] + texts, len(candidates) - len(usable)
