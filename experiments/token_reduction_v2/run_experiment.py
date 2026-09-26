"""token_reduction_v2: correct protocol — Retriever (full repo) → Compressor.

Protocol:
  1. Freeze queries (16 rules from NodeRAG).
  2. Retriever: TF-IDF over ALL repo files → top-10 chunks.
  3. Compressor arms:
     A baseline: no compression (top-10 chunks as-is)
     B exit_50: sentence filter, keep 50% sentences
     C pooling_30: keep top 30% sentences by TF-IDF
     D pooling_50: keep top 50% sentences by TF-IDF
     E hybrid: exit_50 + symbol-matched chunks from full repo
     F rerank: TF-IDF rerank top-10 → top-5
  4. Measure: hit rate (target_file in top-k), tokens, per-rule.
  5. Red team: 6 attacks on experiment integrity.

Deterministic: TF-IDF only, no LLM.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
FROZEN = REPO / "experiments" / "token_reduction_v2" / "frozen"
RESULTS = REPO / "experiments" / "token_reduction_v2" / "results"

STOP = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "need", "dare",
        "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
        "into", "through", "during", "before", "after", "above", "below",
        "between", "and", "but", "or", "nor", "not", "so", "yet", "both",
        "either", "neither", "each", "every", "all", "any", "few", "more",
        "most", "other", "some", "such", "no", "only", "own", "same", "than",
        "too", "very", "just", "because", "if", "when", "while", "that",
        "this", "these", "those", "it", "its", "he", "she", "they", "we",
        "you", "i", "me", "him", "her", "us", "them", "my", "his", "our",
        "your", "their", "what", "which", "who", "whom", "whose", "where",
        "why", "how", "there", "here", "now", "then", "once", "again",
        "further", "also", "about", "up", "out", "off", "over", "under"}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z_][a-z0-9_]+", text.lower()) if t not in STOP and len(t) > 2]


def tfidf_scores(query: str, documents: list[str]) -> list[float]:
    q_terms = set(tokenize(query))
    if not q_terms:
        return [0.0] * len(documents)
    n_docs = len(documents)
    doc_freq: Counter[str] = Counter()
    doc_tokens: list[list[str]] = []
    for doc in documents:
        tokens = tokenize(doc)
        doc_tokens.append(tokens)
        for term in set(tokens) & q_terms:
            doc_freq[term] += 1
    results = []
    for tokens in doc_tokens:
        if not tokens:
            results.append(0.0)
            continue
        term_freq = Counter(tokens)
        score = 0.0
        for term in q_terms:
            if term in term_freq:
                idf = math.log(1 + n_docs / (1 + doc_freq[term]))
                tf = 1 + math.log(term_freq[term])
                score += tf * idf
        results.append(score)
    return results


def sentence_filter(text: str, query: str, keep_ratio: float) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) <= 2:
        return text
    scored = []
    for i, sent in enumerate(sentences):
        toks = tokenize(sent)
        q_toks = tokenize(query)
        if not toks or not q_toks:
            scored.append((i, sent, 0.0))
            continue
        overlap = len(set(toks) & set(q_toks))
        score = overlap / (1 + math.log(1 + len(toks)))
        scored.append((i, sent, score))
    scored.sort(key=lambda x: -x[2])
    keep_n = max(1, int(len(sentences) * keep_ratio))
    kept = {i for i, _, _ in scored[:keep_n]}
    return " ".join(sent for i, sent in enumerate(sentences) if i in kept)


def main() -> int:
    frozen = [json.loads(x) for x in (FROZEN / "rules.jsonl").read_text(encoding="utf-8").strip().splitlines()]
    manifest = json.loads((FROZEN / "manifest.json").read_text(encoding="utf-8"))
    actual_sha = hashlib.sha256((FROZEN / "rules.jsonl").read_bytes()).hexdigest()
    assert actual_sha == manifest["rules_sha256"], f"frozen rules modified: {actual_sha}"

    # Build FULL repo corpus (all .py files)
    chunks: list[str] = []
    chunk_files: list[str] = []
    for py_file in sorted(REPO.rglob("*.py")):
        if ".git" in str(py_file) or "venv" in str(py_file) or "__pycache__" in str(py_file):
            continue
        rel = py_file.relative_to(REPO).as_posix()
        text = py_file.read_text(encoding="utf-8", errors="replace")
        for i in range(0, len(text), 500):
            chunk = text[i:i+500]
            chunks.append(chunk)
            chunk_files.append(rel)

    print(f"Corpus: {len(chunks)} chunks from {len(set(chunk_files))} files")

    results = []
    for rule in frozen:
        q = rule["query"]
        tf = rule.get("target_file")
        control = rule.get("control")

        # Retriever: TF-IDF over full repo
        scores = tfidf_scores(q, chunks)
        scored = sorted(enumerate(scores), key=lambda x: -x[1])
        top10_idx = [i for i, _ in scored[:10]]

        # Arm A: baseline (no compression)
        a_text = " ".join(chunks[i] for i in top10_idx)
        a_tokens = len(tokenize(a_text))
        a_found = (tf in [chunk_files[i] for i in top10_idx]) if tf else False

        # Arm B: exit_50
        b_texts = [sentence_filter(chunks[i], q, 0.5) for i in top10_idx]
        b_text = " ".join(b_texts)
        b_tokens = len(tokenize(b_text))
        b_found = (tf in [chunk_files[i] for i in top10_idx]) if tf else False

        # Arm C: pooling_30
        all_scored = []
        for i in top10_idx:
            sents = re.split(r"(?<=[.!?])\s+", chunks[i])
            for j, sent in enumerate(sents):
                toks = tokenize(sent)
                q_toks = tokenize(q)
                overlap = len(set(toks) & set(q_toks))
                all_scored.append((i, j, sent, overlap))
        all_scored.sort(key=lambda x: -x[3])
        keep_n = max(1, int(len(all_scored) * 0.3))
        kept = {(i, j) for i, j, _, _ in all_scored[:keep_n]}
        c_text = " ".join(sent for i, j, sent, _ in all_scored if (i, j) in kept)
        c_tokens = len(tokenize(c_text))
        c_found = (tf in [chunk_files[i] for i, j, _, _ in all_scored[:keep_n]]) if tf else False

        # Arm D: pooling_50
        keep_n50 = max(1, int(len(all_scored) * 0.5))
        kept50 = {(i, j) for i, j, _, _ in all_scored[:keep_n50]}
        d_text = " ".join(sent for i, j, sent, _ in all_scored if (i, j) in kept50)
        d_tokens = len(tokenize(d_text))
        d_found = (tf in [chunk_files[i] for i, j, _, _ in all_scored[:keep_n50]]) if tf else False

        # Arm E: hybrid (exit_50 + symbol-matched chunks from full repo)
        e_texts = [sentence_filter(chunks[i], q, 0.5) for i in top10_idx]
        q_toks = set(tokenize(q))
        for ci, chunk in enumerate(chunks):
            if ci in top10_idx:
                continue
            c_toks = set(tokenize(chunk))
            if len(q_toks & c_toks) >= 3:
                e_texts.append(sentence_filter(chunk, q, 0.3))
        e_text = " ".join(e_texts)
        e_tokens = len(tokenize(e_text))
        e_found = (tf in [chunk_files[i] for i in top10_idx]) if tf else False

        # Arm F: rerank (top-10 → top-5 by TF-IDF)
        f_idx = top10_idx[:5]
        f_text = " ".join(chunks[i] for i in f_idx)
        f_tokens = len(tokenize(f_text))
        f_found = (tf in [chunk_files[i] for i in f_idx]) if tf else False

        results.append({
            "id": rule["id"], "control": control, "target_file": tf,
            "A_found": a_found, "A_tokens": a_tokens,
            "B_found": b_found, "B_tokens": b_tokens,
            "C_found": c_found, "C_tokens": c_tokens,
            "D_found": d_found, "D_tokens": d_tokens,
            "E_found": e_found, "E_tokens": e_tokens,
            "F_found": f_found, "F_tokens": f_tokens,
        })

    # Aggregate
    rules_only = [r for r in results if not r["control"]]
    pos_controls = [r for r in results if r["control"] == "positive"]
    none_controls = [r for r in results if r["control"] == "none"]

    def agg(rows, arm):
        hits = sum(1 for r in rows if r[f"{arm}_found"])
        tokens = sum(r[f"{arm}_tokens"] for r in rows)
        return {"hits": hits, "total": len(rows), "rate": round(hits / max(1, len(rows)), 4), "tokens": tokens}

    payload = {
        "experiment": "token_reduction_v2",
        "date": "2026-09-27",
        "frozen_rules_sha256": actual_sha,
        "corpus_chunks": len(chunks),
        "corpus_files": len(set(chunk_files)),
        "arms": {f"{arm}": agg(rules_only, arm) for arm in "ABCDEF"},
        "controls": {
            "positive": {arm: agg(pos_controls, arm) for arm in "ABCDEF"},
            "none": {arm: agg(none_controls, arm) for arm in "ABCDEF"},
        },
        "per_rule": results,
    }

    # Red team
    redteam = []
    for rule in frozen:
        tf = rule.get("target_file", "")
        if tf and tf in rule["query"]:
            redteam.append({"attack": "RT1_label_leakage", "rule": rule["id"]})
    if actual_sha != manifest["rules_sha256"]:
        redteam.append({"attack": "RT2_frozen_modified"})
    for arm in "ABCDEF":
        n_hits = sum(1 for r in results if r["control"] == "none" and r[f"{arm}_found"])
        if n_hits > 0:
            redteam.append({"attack": "RT3_none_fp", "arm": arm, "count": n_hits})
        p_miss = sum(1 for r in results if r["control"] == "positive" and not r[f"{arm}_found"])
        if p_miss > 0:
            redteam.append({"attack": "RT4_positive_missed", "arm": arm, "count": p_miss})
    for r in results:
        for arm in "ABCDEF":
            if r[f"{arm}_tokens"] < 0:
                redteam.append({"attack": "RT5_negative_tokens", "rule": r["id"], "arm": arm})
    # RT6: retriever/compressor confusion — target_file in query?
    for rule in frozen:
        tf = rule.get("target_file", "")
        if tf and tf.split("/")[-1].lower() in rule["query"].lower():
            redteam.append({"attack": "RT6_retriever_compressor_confusion", "rule": rule["id"]})

    payload["redteam"] = {"attacks": redteam, "clean": not redteam}

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== TOKEN REDUCTION v2 (full repo) ===")
    for arm, data in payload["arms"].items():
        print(f"  {arm}: {data['hits']}/{data['total']} = {data['rate']*100:.1f}%, tokens={data['tokens']}")
    print(f"  Red team: {'CLEAN' if not redteam else str(len(redteam)) + ' ATTACKS'}")
    for rt in redteam:
        print(f"    {rt['attack']}: {rt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
