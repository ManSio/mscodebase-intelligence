#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FROZEN_RULES = REPO_ROOT / "experiments" / "noderag" / "frozen" / "rules.jsonl"
RESULTS_FILE = REPO_ROOT / "experiments" / "noderag" / "results" / "results.json"
TEMP_GRAPH = REPO_ROOT / "experiments" / "noderag" / "results" / "graph.db"

TARGET_FILES = [
    "src/core/indexing/db_writer.py",
    "src/core/artifact_gc.py",
    "src/providers/reranker/llama_install.py",
    "src/providers/reranker/llama_runner.py",
    "src/providers/embedder/remote_embedder.py",
    "src/core/graph.py",
    "src/core/search/cypher_sql.py",
    "src/core/bootstrap_tests.py",
    "src/core/indexing/freshness.py",
    "src/core/indexing/parser.py",
    "src/core/search/engine.py",
    "src/core/intelligence/verify_on_read.py",
    "src/core/intelligence/layer.py",
    "src/config/settings.py",
    "src/core/indexing/index_project_runner.py",
    "src/core/reindex_ledger.py",
    "src/core/extensions.py",
]


def build_graph() -> "PropertyGraph":
    sys.path.insert(0, str(REPO_ROOT))
    from src.core.graph import PropertyGraph

    if TEMP_GRAPH.exists():
        TEMP_GRAPH.unlink()

    pg = PropertyGraph(TEMP_GRAPH)

    file_symbols: Dict[str, List[Dict]] = {}
    all_symbols: Dict[str, Dict] = {}

    for rel_path in TARGET_FILES:
        full_path = REPO_ROOT / rel_path
        if not full_path.exists():
            continue
        try:
            source = full_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel_path)
        except (SyntaxError, UnicodeDecodeError):
            continue

        symbols = extract_symbols(tree, rel_path, source)
        file_symbols[rel_path] = symbols
        for sym in symbols:
            qname = sym["qualified_name"]
            all_symbols[qname] = sym

    for rel_path in file_symbols:
        pg.add_node(
            name=rel_path,
            label="FILE",
            qualified_name=f"file:{rel_path}",
            file_path=rel_path,
            properties={"type": "file"},
        )

    for qname, sym in all_symbols.items():
        pg.add_node(
            name=sym["name"],
            label=sym["label"],
            qualified_name=qname,
            file_path=sym["file_path"],
            properties={
                "type": sym["type"],
                "file_path": sym["file_path"],
                "line": sym.get("line", 0),
            },
        )

    for qname, sym in all_symbols.items():
        pg.add_edge(
            source_qname=f"file:{sym['file_path']}",
            target_qname=qname,
            type="CONTAINS",
        )

    for qname, sym in all_symbols.items():
        for callee in sym.get("calls", []):
            if callee in all_symbols:
                pg.add_edge(
                    source_qname=qname,
                    target_qname=callee,
                    type="CALLS",
                )

    for rel_path, symbols in file_symbols.items():
        for imp in symbols[0].get("imports", []) if symbols else []:
            for target in TARGET_FILES:
                if imp in target or target.endswith(imp):
                    pg.add_edge(
                        source_qname=f"file:{rel_path}",
                        target_qname=f"file:{target}",
                        type="IMPORTS",
                    )
                    break

    return pg


def extract_symbols(tree: ast.AST, file_path: str, source: str) -> List[Dict]:
    symbols = []
    lines = source.split("\n")

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body_lines = lines[node.lineno - 1 : node.end_lineno or node.lineno]
            text = "\n".join(body_lines)
            symbols.append({
                "name": node.name,
                "label": "FUNCTION",
                "type": "function",
                "qualified_name": f"{file_path}.{node.name}",
                "file_path": file_path,
                "line": node.lineno,
                "text": text,
                "calls": extract_calls(node),
                "imports": [],
            })
        elif isinstance(node, ast.ClassDef):
            body_lines = lines[node.lineno - 1 : node.end_lineno or node.lineno]
            text = "\n".join(body_lines)
            symbols.append({
                "name": node.name,
                "label": "CLASS",
                "type": "class",
                "qualified_name": f"{file_path}.{node.name}",
                "file_path": file_path,
                "line": node.lineno,
                "text": text,
                "calls": extract_calls(node),
                "imports": [],
            })

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    if symbols:
        symbols[0]["imports"] = imports

    return symbols


def extract_calls(node: ast.AST) -> List[str]:
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.append(child.func.attr)
    return list(set(calls))


class TFIDFRetriever:
    def __init__(self, chunks: List[Dict]):
        self.chunks = chunks
        self.df: Dict[str, int] = defaultdict(int)
        self.doc_vectors: List[Dict[str, float]] = []
        self._build_index()

    def _build_index(self):
        for chunk in self.chunks:
            text = chunk["text"].lower()
            words = set(re.findall(r"[a-z_]+", text))
            for w in words:
                self.df[w] += 1
        n = len(self.chunks)
        for chunk in self.chunks:
            text = chunk["text"].lower()
            words = re.findall(r"[a-z_]+", text)
            tf: Dict[str, float] = defaultdict(float)
            for w in words:
                tf[w] += 1
            vec = {}
            for w, count in tf.items():
                idf = math.log((n + 1) / (self.df.get(w, 0) + 1)) + 1
                vec[w] = count * idf
            self.doc_vectors.append(vec)

    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        query_words = re.findall(r"[a-z_]+", query.lower())
        qvec: Dict[str, float] = defaultdict(float)
        for w in query_words:
            qvec[w] += 1

        scores = []
        for i, dvec in enumerate(self.doc_vectors):
            score = 0.0
            for w, qweight in qvec.items():
                if w in dvec:
                    score += qweight * dvec[w]
            if score > 0:
                scores.append((i, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in scores[:top_k]:
            chunk = self.chunks[idx].copy()
            chunk["score"] = score
            results.append(chunk)
        return results


def graph_traverse(pg: "PropertyGraph", start_symbol: str, max_depth: int = 3) -> Set[str]:
    start_node = None
    nodes = pg.find_nodes(name_pattern=f"%{start_symbol}%", limit=5)
    if nodes:
        start_node = nodes[0]

    if not start_node:
        return set()

    visited: Set[str] = set()
    queue: List[Tuple[str, int]] = [(start_node.qualified_name, 0)]
    visited_files: Set[str] = set()

    conn = sqlite3.connect(str(TEMP_GRAPH))
    conn.row_factory = sqlite3.Row

    while queue:
        qname, depth = queue.pop(0)
        if qname in visited or depth > max_depth:
            continue
        visited.add(qname)

        row = conn.execute(
            "SELECT id, name, label, qualified_name, file_path FROM nodes WHERE qualified_name = ?",
            (qname,),
        ).fetchone()
        if row:
            if row["file_path"]:
                visited_files.add(row["file_path"])
            if row["label"] == "FILE":
                visited_files.add(row["name"])

        node_id = row["id"] if row else None
        if node_id:
            edge_rows = conn.execute(
                "SELECT source_id, target_id, type FROM edges WHERE source_id = ? OR target_id = ?",
                (node_id, node_id),
            ).fetchall()
            for er in edge_rows:
                if er["source_id"] == node_id:
                    tgt = conn.execute(
                        "SELECT qualified_name FROM nodes WHERE id = ?", (er["target_id"],)
                    ).fetchone()
                    if tgt:
                        queue.append((tgt["qualified_name"], depth + 1))
                if er["target_id"] == node_id:
                    src = conn.execute(
                        "SELECT qualified_name FROM nodes WHERE id = ?", (er["source_id"],)
                    ).fetchone()
                    if src:
                        queue.append((src["qualified_name"], depth + 1))

    conn.close()
    return visited_files


def count_tokens(text: str) -> int:
    words = len(text.split())
    return int(words * 1.3)


def main():
    sys.path.insert(0, str(REPO_ROOT))
    from src.core.graph import PropertyGraph

    rules = []
    with open(FROZEN_RULES, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rules.append(json.loads(line))

    print(f"Loaded {len(rules)} frozen rules")
    print(f"SHA256: {hashlib.sha256(FROZEN_RULES.read_bytes()).hexdigest()}")

    print("\nBuilding PropertyGraph...")
    pg = build_graph()
    print(f"Graph built at {TEMP_GRAPH}")

    chunks = []
    for rel_path in TARGET_FILES:
        full_path = REPO_ROOT / rel_path
        if not full_path.exists():
            continue
        try:
            source = full_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel_path)
        except (SyntaxError, UnicodeDecodeError):
            continue
        symbols = extract_symbols(tree, rel_path, source)
        for sym in symbols:
            chunks.append({
                "file_path": rel_path,
                "symbol": sym["name"],
                "text": f"{sym['name']} {sym['text']}",
                "label": sym["type"],
            })

    print(f"Built {len(chunks)} chunks for Arm A")

    retriever = TFIDFRetriever(chunks)

    results = []
    for rule in rules:
        rule_id = rule["id"]
        query = rule["query"]
        target_file = rule.get("target_file")
        arm_b_start = rule.get("arm_b_start")
        control = rule.get("control")

        print(f"\n--- {rule_id}: {rule['rule'][:60]}...")

        arm_a_results = retriever.search(query, top_k=10)
        arm_a_files = [r["file_path"] for r in arm_a_results]
        arm_a_hit = target_file in arm_a_files if target_file else False
        arm_a_tokens = sum(count_tokens(r["text"]) for r in arm_a_results)

        if arm_b_start:
            arm_b_files = graph_traverse(pg, arm_b_start, max_depth=3)
            arm_b_hit = target_file in arm_b_files if target_file else False
            arm_b_tokens = 0
            for fp in arm_b_files:
                full_path = REPO_ROOT / fp
                if full_path.exists():
                    arm_b_tokens += count_tokens(full_path.read_text(encoding="utf-8"))
        else:
            arm_b_files = set()
            arm_b_hit = False
            arm_b_tokens = 0

        result = {
            "id": rule_id,
            "rule": rule["rule"],
            "query": query,
            "target_file": target_file,
            "control": control,
            "file_found_by_A": arm_a_hit,
            "file_found_by_B": arm_b_hit,
            "tokens_A": arm_a_tokens,
            "tokens_B": arm_b_tokens,
            "arm_a_top_files": arm_a_files[:5],
            "arm_b_visited_files": list(arm_b_files)[:10],
            "arm_b_start": arm_b_start,
        }
        results.append(result)

        print(f"  A: hit={arm_a_hit}, tokens={arm_a_tokens}, top_files={arm_a_files[:3]}")
        print(f"  B: hit={arm_b_hit}, tokens={arm_b_tokens}, visited={len(arm_b_files)} files")

    rule_results = [r for r in results if r["control"] is None]
    positive_controls = [r for r in results if r["control"] == "positive"]
    none_controls = [r for r in results if r["control"] == "none"]

    a_hits = sum(1 for r in rule_results if r["file_found_by_A"])
    b_hits = sum(1 for r in rule_results if r["file_found_by_B"])
    a_hit_rate = a_hits / len(rule_results) if rule_results else 0
    b_hit_rate = b_hits / len(rule_results) if rule_results else 0

    a_tokens_total = sum(r["tokens_A"] for r in rule_results)
    b_tokens_total = sum(r["tokens_B"] for r in rule_results)

    positive_passed = sum(1 for r in positive_controls if r["file_found_by_A"] or r["file_found_by_B"])
    none_clean = sum(1 for r in none_controls if not r["file_found_by_A"] and not r["file_found_by_B"])

    if b_hit_rate > a_hit_rate:
        verdict = "CONFIRMED"
    elif a_hit_rate >= b_hit_rate:
        verdict = "REFUTED"
    else:
        verdict = "MIXED"

    output = {
        "experiment": "noderag_deterministic",
        "date": "2026-09-27",
        "frozen_rules_sha256": hashlib.sha256(FROZEN_RULES.read_bytes()).hexdigest(),
        "total_rules": len(rules),
        "results": results,
        "aggregate": {
            "A_hit_rate": round(a_hit_rate, 4),
            "B_hit_rate": round(b_hit_rate, 4),
            "A_tokens": a_tokens_total,
            "B_tokens": b_tokens_total,
            "A_hits": a_hits,
            "B_hits": b_hits,
            "total_rule_queries": len(rule_results),
        },
        "controls": {
            "positive_controls_passed": positive_passed,
            "positive_controls_total": len(positive_controls),
            "none_controls_clean": none_clean,
            "none_controls_total": len(none_controls),
        },
        "verdict": verdict,
    }

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"Rule queries: {len(rule_results)}")
    print(f"Arm A (chunked): {a_hits}/{len(rule_results)} = {a_hit_rate:.1%}")
    print(f"Arm B (graph):   {b_hits}/{len(rule_results)} = {b_hit_rate:.1%}")
    print(f"Arm A tokens: {a_tokens_total}")
    print(f"Arm B tokens: {b_tokens_total}")
    print(f"Positive controls: {positive_passed}/{len(positive_controls)}")
    print(f"NONE controls clean: {none_clean}/{len(none_controls)}")
    print(f"Verdict: {verdict}")
    print(f"\nResults written to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
