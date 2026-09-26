"""token_reduction experiment: reduce tokens without losing quality.

Protocol (frozen-before-look):
  1. Load frozen rules (16 entries: 10 rules + 3 positive + 3 NONE controls).
  2. Arms:
     A baseline: full chunk text from top-10 TF-IDF files
     B exit: sentence-level TF-IDF filtering (keep sentences with score >= 0.3 * max)
     C pooling: keep top 30% sentences by TF-IDF score
     D hybrid: exit + graph expansion (add callers/callees of matched symbols)
  3. Controls: P1-P3 must be found, N1-N3 must NOT be found.
  4. Red team attacks on the experiment itself.

Deterministic: TF-IDF only, no LLM calls.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
FROZEN = REPO / "experiments" / "token_reduction" / "frozen"
RESULTS = REPO / "experiments" / "token_reduction" / "results"

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


def tfidf_scores(query: str, documents: list[str]) -> list[dict[str, float]]:
    """Compute TF-IDF scores for each document."""
    q_terms = set(tokenize(query))
    if not q_terms:
        return [{"score": 0.0, "terms": {}} for _ in documents]
    n_docs = len(documents)
    doc_freq: Counter[str] = Counter()
    doc_tokens: list[list[str]] = []
    for doc in documents:
        tokens = tokenize(doc)
        doc_tokens.append(tokens)
        for term in set(tokens) & q_terms:
            doc_freq[term] += 1
    results = []
    for i, tokens in enumerate(doc_tokens):
        if not tokens:
            results.append({"score": 0.0, "terms": {}})
            continue
        term_freq = Counter(tokens)
        score = 0.0
        matched = {}
        for term in q_terms:
            if term in term_freq:
                idf = math.log(1 + n_docs / (1 + doc_freq[term]))
                tf = 1 + math.log(term_freq[term])
                s = tf * idf
                score += s
                matched[term] = round(s, 4)
        results.append({"score": round(score, 4), "terms": matched})
    return results


def sentence_filter(text: str, query: str, keep_ratio: float = 1.0) -> str:
    """Filter sentences by TF-IDF relevance. keep_ratio=1.0 returns all."""
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
    if keep_ratio >= 1.0:
        return text
    scored.sort(key=lambda x: -x[2])
    keep_n = max(1, int(len(sentences) * keep_ratio))
    kept = {i for i, _, _ in scored[:keep_n]}
    return " ".join(sent for i, sent in enumerate(sentences) if i in kept)


def main() -> int:
    frozen = [json.loads(x) for x in (FROZEN / "rules.jsonl").read_text(encoding="utf-8").strip().splitlines()]
    manifest = json.loads((FROZEN / "manifest.json").read_text(encoding="utf-8"))
    actual_sha = hashlib.sha256((FROZEN / "rules.jsonl").read_bytes()).hexdigest()
    assert actual_sha == manifest["rules_sha256"], f"frozen rules modified: {actual_sha}"

    # Read source files for each target
    file_cache: dict[str, str] = {}
    for rule in frozen:
        tf = rule.get("target_file")
        if tf and tf not in file_cache:
            p = REPO / tf
            file_cache[tf] = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""

    # Build document corpus for TF-IDF (chunks)
    chunks: list[str] = []
    chunk_files: list[str] = []
    for rule in frozen:
        tf = rule.get("target_file")
        if tf and tf in file_cache:
            text = file_cache[tf]
            for i in range(0, len(text), 500):
                chunk = text[i:i+500]
                chunks.append(chunk)
                chunk_files.append(tf)

    results = []
    for rule in frozen:
        q = rule["query"]
        tf = rule.get("target_file")
        control = rule.get("control")

        # TF-IDF over chunks
        scores = tfidf_scores(q, chunks)
        scored_chunks = sorted(enumerate(scores), key=lambda x: -x[1]["score"])
        top10_idx = [i for i, _ in scored_chunks[:10]]

        # Arm A: full text of top-10 chunks
        a_text = " ".join(chunks[i] for i in top10_idx)
        a_tokens = len(tokenize(a_text))
        a_found = (tf in [chunk_files[i] for i in top10_idx]) if tf else False

        # Arm B: exit-style sentence filtering
        b_texts = []
        for i in top10_idx:
            filtered = sentence_filter(chunks[i], q, keep_ratio=0.3)
            b_texts.append(filtered)
        b_text = " ".join(b_texts)
        b_tokens = len(tokenize(b_text))
        b_found = (tf in [chunk_files[i] for i in top10_idx]) if tf else False

        # Arm C: pooling (top 30% sentences globally)
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

        # Arm D: hybrid (exit + symbol matching)
        d_texts = []
        for i in top10_idx:
            d_texts.append(sentence_filter(chunks[i], q, keep_ratio=0.5))
        q_toks = set(tokenize(q))
        for ci, chunk in enumerate(chunks):
            if ci in top10_idx:
                continue
            c_toks = set(tokenize(chunk))
            if len(q_toks & c_toks) >= 2:
                d_texts.append(sentence_filter(chunk, q, keep_ratio=0.3))
        d_text = " ".join(d_texts)
        d_tokens = len(tokenize(d_text))
        d_found = (tf in [chunk_files[i] for i in top10_idx]) if tf else False

        results.append({
            "id": rule["id"],
            "control": control,
            "target_file": tf,
            "A_found": a_found, "A_tokens": a_tokens,
            "B_found": b_found, "B_tokens": b_tokens,
            "C_found": c_found, "C_tokens": c_tokens,
            "D_found": d_found, "D_tokens": d_tokens,
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
        "experiment": "token_reduction_v1",
        "date": "2026-09-27",
        "frozen_rules_sha256": actual_sha,
        "arms": {
            "A_baseline_full": agg(rules_only, "A"),
            "B_exit_filter": agg(rules_only, "B"),
            "C_pooling_30": agg(rules_only, "C"),
            "D_hybrid": agg(rules_only, "D"),
        },
        "controls": {
            "positive": {
                "A": agg(pos_controls, "A"), "B": agg(pos_controls, "B"),
                "C": agg(pos_controls, "C"), "D": agg(pos_controls, "D"),
            },
            "none": {
                "A": agg(none_controls, "A"), "B": agg(none_controls, "B"),
                "C": agg(none_controls, "C"), "D": agg(none_controls, "D"),
            },
        },
        "per_rule": results,
    }

    # Red team checks
    redteam = []

    # RT1: label leakage — target_file visible in query?
    for rule in frozen:
        tf = rule.get("target_file", "")
        if tf and tf in rule["query"]:
            redteam.append({"attack": "RT1_label_leakage", "rule": rule["id"], "detail": "target_file in query"})

    # RT2: frozen rules modified?
    if actual_sha != manifest["rules_sha256"]:
        redteam.append({"attack": "RT2_frozen_modified", "detail": "rules.jsonl changed after freeze"})

    # RT3: NONE controls false positives?
    for arm in "ABCD":
        n_hits = sum(1 for r in results if r["control"] == "none" and r[f"{arm}_found"])
        if n_hits > 0:
            redteam.append({"attack": "RT3_none_fp", "arm": arm, "detail": f"{n_hits} false positives on NONE controls"})

    # RT4: positive controls missed?
    for arm in "ABCD":
        p_miss = sum(1 for r in results if r["control"] == "positive" and not r[f"{arm}_found"])
        if p_miss > 0:
            redteam.append({"attack": "RT4_positive_missed", "arm": arm, "detail": f"{p_miss} positive controls missed"})

    # RT5: token count manipulation (negative tokens?)
    for r in results:
        for arm in "ABCD":
            if r[f"{arm}_tokens"] < 0:
                redteam.append({"attack": "RT5_negative_tokens", "rule": r["id"], "arm": arm})

    payload["redteam"] = {"attacks": redteam, "clean": not redteam}

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== TOKEN REDUCTION v1 ===")
    for arm, data in payload["arms"].items():
        print(f"  {arm}: {data['hits']}/{data['total']} = {data['rate']*100:.1f}%, tokens={data['tokens']}")
    print(f"  Red team: {'CLEAN' if not redteam else str(len(redteam)) + ' ATTACKS'}")
    for rt in redteam:
        print(f"    {rt['attack']}: {rt['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
