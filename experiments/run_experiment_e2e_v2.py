#!/usr/bin/env python3
"""
E2E Experiment v2: Using the SAME dense graph as v3/v4 experiments.
"""
import sys, json, time, random, ast
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

GOLD_STANDARD = {
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
    "EmbeddingCache": "src/core/intelligence/layer.py",
    "ProjectIndexerRegistry": "src/core/indexing/project_indexer_registry.py",
    "how does the search pipeline work": "src/core/search/engine.py",
    "how is the index built": "src/core/indexing/indexer.py",
    "how does the rate limiter work": "src/core/rate_limiter.py",
    "how does the watchdog monitor health": "src/core/indexing/resource_monitor.py",
    "how does error handling work": "src/core/error_handler.py",
    "how does the MCP server start": "src/mcp/server.py",
    "how does file watching work": "src/core/indexing/watchdog.py",
    "how does the installer work": "install.py",
    "how does i18n work": "src/utils/i18n.py",
    "how does the sandbox execute code": "src/core/sandbox/executor.py",
    "who calls hybrid_search": "src/core/search/engine.py",
    "who uses LanceDB": "src/core/indexing/db_manager.py",
    "who imports the config": "src/config/settings.py",
    "who calls the reranker": "src/providers/reranker.py",
    "who uses asyncio locks": "src/core/runtime_coordinator.py",
    "who calls embedding_cache": "src/core/intelligence/engine.py",
    "who uses the watchdog": "src/core/indexing/resource_monitor.py",
    "who calls notify_change": "src/core/indexing/indexer.py",
    "who imports error_handler": "src/core/error_handler.py",
    "who calls search_code": "src/mcp/tools/search_tools.py",
    "what are the main layers of the project": "src/core/runtime_coordinator.py",
    "what is the entry point": "src/mcp/server.py",
    "what files are in core": "src/core/__init__.py",
    "what is the dependency graph": "src/core/indexing/db_manager.py",
    "what are the hotspots": "src/core/intelligence/layer.py",
    "what tests exist": "src/__init__.py",
    "what is the project structure": "src/__init__.py",
    "what are the external dependencies": "src/mcp/server.py",
    "what database is used": "src/core/indexing/db_manager.py",
    "what models are loaded": "src/providers/embedder/remote_embedder.py",
    "where could a race condition happen": "src/core/rate_limiter.py",
    "where is memory managed": "src/core/intelligence/engine.py",
    "where are timeouts configured": "src/config/settings.py",
    "where is logging configured": "src/core/log_manager.py",
    "where are SQL queries built": "src/core/indexing/db_manager.py",
}

def scan_files():
    files = {}
    for py in sorted(SRC.rglob("*.py")):
        if "__pycache__" in str(py): continue
        rel = str(py.relative_to(PROJECT)).replace("\\", "/")
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)
        except: continue
        imps, dc, df, uc, uf = [], set(), set(), set(), set()
        for n in ast.iter_child_nodes(tree):
            if isinstance(n, ast.Import):
                for a in n.names: imps.append(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module:
                imps.append(n.module.split(".")[0])
            elif isinstance(n, ast.ClassDef): dc.add(n.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): df.add(n.name)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name): uf.add(n.func.id)
                elif isinstance(n.func, ast.Attribute): uf.add(n.func.attr)
            elif isinstance(n, ast.Name) and n.id[0].isupper(): uc.add(n.id)
        files[rel] = dict(content=content, tokens=len(ENC.encode(content)),
            lines=len(content.splitlines()), imps=imps, dc=dc, df=df, uc=uc, uf=uf)
    return files

def build_dense_graph_v4(files):
    """Same as v3/v4: imports + class refs + function calls"""
    G = nx.DiGraph()
    for p in files: G.add_node(p, tokens=files[p]["tokens"])
    
    # Imports
    for path, data in files.items():
        for im in data["imps"]:
            for c in files:
                if c!=path and (c.replace("/",".").endswith(im) or im in c.split("/")[-1].replace(".py","")):
                    G.add_edge(path, c, type="import"); break
    
    # Class refs
    cm = defaultdict(set)
    for p,d in files.items():
        for c in d["dc"]: cm[c].add(p)
    for path, data in files.items():
        for c in data["uc"]:
            for t in cm.get(c, set()):
                if t != path: G.add_edge(path, t, type="class_ref"); break
    
    # Function calls
    fm = defaultdict(set)
    for p,d in files.items():
        for f in d["df"]: fm[f].add(p)
    for path, data in files.items():
        for f in data["uf"]:
            for t in fm.get(f, set()):
                if t != path: G.add_edge(path, t, type="func_call"); break
    
    return G

def select_top20(pr_scores, files):
    sorted_pr = sorted(pr_scores.items(), key=lambda x: x[1], reverse=True)
    n = max(1, int(len(sorted_pr) * 0.20))
    return set(p for p,_ in sorted_pr[:n])

def select_random_top20(files):
    all_files = list(files.keys())
    random.shuffle(all_files)
    n = max(1, int(len(all_files) * 0.20))
    return set(all_files[:n])

def select_rag_top20(files, query):
    query_words = set(w.lower() for w in query.split() if len(w) > 2)
    scores = {}
    for path, data in files.items():
        cl = data["content"].lower()
        score = sum(1 for w in query_words if w in cl)
        if score > 0: scores[path] = score
    sorted_files = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    n = max(1, int(len(files) * 0.20))
    return set(p for p,_ in sorted_files[:n])

def heuristic_judge(gold_file, selected):
    if gold_file in selected: return "SUFFICIENT"
    for p in selected:
        if gold_file in p or p in gold_file: return "PARTIAL"
    return "INSUFFICIENT"

def build_context(files, selected, max_tokens=70000):
    parts = []
    total = 0
    for path in selected:
        if path in files:
            tok = files[path]["tokens"]
            if total + tok > max_tokens: break
            parts.append(f"=== {path} ===\n{files[path]['content']}\n")
            total += tok
    return "\n".join(parts), total

def main():
    print("="*70)
    print("E2E EXPERIMENT v2: Dense Graph (same as v3/v4)")
    print("="*70)

    files = scan_files()
    print(f"Files: {len(files)}, Queries: {len(GOLD_STANDARD)}")

    graph = build_dense_graph_v4(files)
    print(f"Graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

    pr = nx.pagerank(graph, alpha=0.85)

    results = {"pagerank": [], "random": [], "rag": []}

    for query, gold_file in GOLD_STANDARD.items():
        pr_sel = select_top20(pr, files)
        rand_sel = select_random_top20(files)
        rag_sel = select_rag_top20(files, query)

        for method_name, sel in [("pagerank", pr_sel), ("random", rand_sel), ("rag", rag_sel)]:
            verdict = heuristic_judge(gold_file, sel)
            ctx, tok = build_context(files, sel)
            results[method_name].append({
                "query": query, "gold": gold_file, "verdict": verdict,
                "tokens": tok, "files_selected": len(sel), "in_selection": gold_file in sel
            })

    print("\n" + "="*70)
    print("SUMMARY (Dense Graph)")
    print("="*70)
    for method in ["pagerank", "random", "rag"]:
        v = results[method]
        suff = sum(1 for r in v if r["verdict"] == "SUFFICIENT")
        part = sum(1 for r in v if r["verdict"] == "PARTIAL")
        insuff = sum(1 for r in v if r["verdict"] == "INSUFFICIENT")
        avg_tok = sum(r["tokens"] for r in v) / len(v)
        hit = sum(1 for r in v if r["in_selection"])
        print(f"  {method:8s}: SUFF={suff:2d}  PART={part:2d}  INSUFF={insuff:2d}  "
              f"Hit@Gold={hit}/{len(v)}  AvgTok={avg_tok:,.0f}")

    out = PROJECT / "experiments" / "e2e_results_v2.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults: {out}")

if __name__ == "__main__":
    main()