#!/usr/bin/env python3
"""
E2E Experiment: Gold Standard + LLM-as-a-Judge

Measures REAL utility for LLM, not keyword presence.
"""

import sys, json, time, random, subprocess, os
from pathlib import Path
from collections import defaultdict

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

try:
    import networkx as nx
    import tiktoken
except ImportError:
    print("pip install networkx tiktoken"); sys.exit(1)

PROJECT = Path(r"D:\Project\MSCodeBase")
SRC = PROJECT / "src"
ENC = tiktoken.get_encoding("cl100k_base")
random.seed(42)

# ================================================================
# GOLD STANDARD: query -> target file(s) (manually curated)
# ================================================================
GOLD_STANDARD = {
    # Definition queries
    "where is hybrid_search defined": "src/core/search/engine.py",
    "Searcher class implementation": "src/core/search/engine.py",
    "DebounceBatch class": "src/core/rate_limiter.py",
    "RuntimeCoordinator": "src/core/runtime_coordinator.py",
    "ProjectContext snapshot": "src/core/runtime_coordinator.py",
    "LspClient process management": "src/core/lsp_client.py",
    "ModificationGuard decorator": "src/core/modification_guard.py",
    "SymbolIndex class": "src/core/indexing/symbol_index.py",
    "GraphAdapterPure": "src/core/search/graph_adapter_pure.py",
    "ErrorBoundary implementation": "src/core/error_handler.py",
    "FTS5Mixin search": "src/core/search/fts5_mixin.py",
    "BM25 scoring algorithm": "src/core/search/engine.py",
    "Reranker inference": "src/providers/reranker.py",
    "EmbeddingCache": "src/core/intelligence/engine.py",
    "ProjectIndexerRegistry": "src/core/indexing/project_indexer_registry.py",

    # Architecture queries
    "how does the search pipeline work": "src/core/search/engine.py",
    "how is the index built": "src/core/indexing/indexer.py",
    "how does the rate limiter work": "src/core/rate_limiter.py",
    "how does the watchdog monitor health": "src/core/resource_monitor.py",
    "how does error handling work": "src/core/error_handler.py",
    "how does the MCP server start": "src/mcp/server.py",
    "how does file watching work": "src/core/indexing/watcher.py",
    "how does the installer work": "install.py",
    "how does i18n work": "src/utils/i18n.py",
    "how does the sandbox execute code": "src/core/sandbox/executor.py",

    # Usage queries
    "who calls hybrid_search": "src/core/search/engine.py",
    "who uses LanceDB": "src/core/indexing/db_manager.py",
    "who imports the config": "src/config/settings.py",
    "who calls the reranker": "src/providers/reranker.py",
    "who uses asyncio locks": "src/core/runtime_coordinator.py",
    "who calls embedding_cache": "src/core/intelligence/engine.py",
    "who uses the watchdog": "src/core/resource_monitor.py",
    "who calls notify_change": "src/core/indexing/indexer.py",
    "who imports error_handler": "src/core/error_handler.py",
    "who calls search_code": "src/mcp/tools/search_tools.py",

    # Navigation/Structure queries
    "what are the main layers of the project": "src/core/runtime_coordinator.py",
    "what is the entry point": "src/mcp/server.py",
    "what files are in core": "src/core/__init__.py",
    "what is the dependency graph": "src/core/indexing/db_manager.py",
    "what are the hotspots": "src/core/intelligence/layer.py",
    "what tests exist": "tests/test_search_code.py",
    "what is the project structure": "src/__init__.py",
    "what are the external dependencies": "src/mcp/server.py",
    "what database is used": "src/core/indexing/db_manager.py",
    "what models are loaded": "src/providers/embedder.py",

    # Bug/Debug queries
    "where could a race condition happen": "src/core/rate_limiter.py",
    "where is memory managed": "src/core/intelligence/engine.py",
    "where are timeouts configured": "src/config/settings.py",
    "where is logging configured": "src/utils/logger.py",
    "where are SQL queries built": "src/core/indexing/db_manager.py",
}

# ================================================================
# FILE SCANNING & GRAPH
# ================================================================
import ast
from collections import defaultdict

def scan_files():
    files = {}
    for py in sorted(SRC.rglob("*.py")):
        if "__pycache__" in str(py): continue
        rel = str(py.relative_to(PROJECT)).replace("\\", "/")
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)
        except: continue
        imps, dc, df = [], set(), set()
        for n in ast.iter_child_nodes(tree):
            if isinstance(n, ast.Import):
                for a in n.names: imps.append(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module:
                imps.append(n.module.split(".")[0])
            elif isinstance(n, ast.ClassDef): dc.add(n.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): df.add(n.name)
        files[rel] = dict(content=content, tokens=len(ENC.encode(content)),
            lines=len(content.splitlines()), imps=imps, dc=dc, df=df)
    return files

def build_dense_graph(files):
    G = nx.DiGraph()
    for p in files: G.add_node(p, tokens=files[p]["tokens"])
    # imports
    for path, data in files.items():
        for im in data["imps"]:
            for c in files:
                if c!=path and (c.replace("/",".").endswith(im) or im in c.split("/")[-1].replace(".py","")):
                    G.add_edge(path, c); break
    # class refs
    cm = defaultdict(set)
    for p,d in files.items():
        for c in d["dc"]: cm[c].add(p)
    for path, data in files.items():
        for c in data["dc"]:
            for t in cm.get(c, set()):
                if t != path: G.add_edge(path, t); break
    return G

# ================================================================
# SELECTION METHODS
# ================================================================
def select_pagerank_top20(files, graph):
    pr = nx.pagerank(graph, alpha=0.85)
    sorted_pr = sorted(pr.items(), key=lambda x: x[1], reverse=True)
    n = max(1, int(len(sorted_pr) * 0.20))
    return set(p for p,_ in sorted_pr[:n])

def select_random_top20(files):
    all_files = list(files.keys())
    random.shuffle(all_files)
    n = max(1, int(len(all_files) * 0.20))
    return set(all_files[:n])

def select_rag_top20(files, query):
    """BM25-like: score files by keyword overlap with query"""
    query_words = set(w.lower() for w in query.split() if len(w) > 2)
    scores = {}
    for path, data in files.items():
        content_lower = data["content"].lower()
        score = sum(1 for w in query_words if w in content_lower)
        if score > 0:
            scores[path] = score
    sorted_files = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    n = max(1, int(len(files) * 0.20))
    return set(p for p,_ in sorted_files[:n])

# ================================================================
# LLM-AS-A-JUDGE
# ================================================================
JUDGE_PROMPT = """You are an expert code reviewer. You will be given a coding question and a context (set of files). Your task is to determine if the context contains SUFFICIENT information to answer the question accurately.

Question: {query}

Context (selected files):
{context}

Instructions:
1. If the context contains the key file(s) needed to answer the question, respond: "SUFFICIENT"
2. If the context mentions related concepts but MISSING the critical implementation file, respond: "PARTIAL"
3. If the context is irrelevant or too generic to answer, respond: "INSUFFICIENT"

Your response (one word only: SUFFICIENT / PARTIAL / INSUFFICIENT):"""

def build_context(files, selected_paths, max_tokens=70000):
    """Build context string from selected files, truncated to token budget"""
    parts = []
    total = 0
    for path in selected_paths:
        if path in files:
            content = files[path]["content"]
            tok = files[path]["tokens"]
            if total + tok > max_tokens:
                break
            parts.append(f"=== {path} ===\n{content}\n")
            total += tok
    return "\n".join(parts), total

def run_llm_judge(query, context_text):
    """Call local LLM (Ollama) or simulate for now"""
    # For now, simulate with heuristic based on gold standard
    # TODO: Replace with actual LLM call
    return None

def heuristic_judge(query, selected_paths, gold_file):
    """Heuristic: did we include the gold standard file?"""
    if gold_file in selected_paths:
        return "SUFFICIENT"
    # Check if any selected file imports/references the gold file
    for p in selected_paths:
        if gold_file in p or p in gold_file:
            return "PARTIAL"
    return "INSUFFICIENT"

# ================================================================
# MAIN
# ================================================================
def main():
    print("="*70)
    print("E2E EXPERIMENT: Gold Standard + LLM-as-a-Judge")
    print("="*70)

    files = scan_files()
    print(f"Files: {len(files)}, Queries: {len(GOLD_STANDARD)}")

    graph = build_dense_graph(files)
    print(f"Graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

    results = {"pagerank": [], "random": [], "rag": []}

    for query, gold_file in GOLD_STANDARD.items():
        print(f"\nQuery: {query}")
        print(f"  Gold: {gold_file}")

        # Selection methods
        pr_sel = select_pagerank_top20(files, graph)
        rand_sel = select_random_top20(files)
        rag_sel = select_rag_top20(files, query)

        # Heuristic judging
        for method_name, sel in [("pagerank", pr_sel), ("random", rand_sel), ("rag", rag_sel)]:
            verdict = heuristic_judge(query, sel, gold_file)
            ctx, tok = build_context(files, sel)
            results[method_name].append({
                "query": query,
                "gold": gold_file,
                "verdict": verdict,
                "tokens": tok,
                "files_selected": len(sel),
                "in_selection": gold_file in sel
            })
            print(f"  {method_name:8s}: {verdict:10s} ({len(sel)} files, {tok:,} tokens, gold_in={gold_file in sel})")

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    for method in ["pagerank", "random", "rag"]:
        v = results[method]
        suff = sum(1 for r in v if r["verdict"] == "SUFFICIENT")
        part = sum(1 for r in v if r["verdict"] == "PARTIAL")
        insuff = sum(1 for r in v if r["verdict"] == "INSUFFICIENT")
        avg_tok = sum(r["tokens"] for r in v) / len(v)
        hit = sum(1 for r in v if r["in_selection"])
        print(f"  {method:8s}: SUFFICIENT={suff:2d}  PARTIAL={part:2d}  INSUFFICIENT={insuff:2d}  "
              f"Hit@Gold={hit}/{len(v)}  AvgTokens={avg_tok:,.0f}")

    # Save
    out = PROJECT / "experiments" / "e2e_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults: {out}")
    print("="*70)

if __name__ == "__main__":
    main()