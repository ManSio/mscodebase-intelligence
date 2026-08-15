#!/usr/bin/env python3
"""E2E with both sparse and dense graphs for comparison."""
import sys, json, random, ast
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

GOLD = {
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
    "where could a race condition happen": "src/core/rate_limiter.py",
    "where is memory managed": "src/core/intelligence/engine.py",
    "where are timeouts configured": "src/config/settings.py",
    "where is logging configured": "src/utils/logger.py",
    "where are SQL queries built": "src/core/indexing/db_manager.py",
}

def scan():
    files = {}
    for py in sorted(SRC.rglob("*.py")):
        if "__pycache__" in str(py): continue
        rel = str(py.relative_to(PROJECT)).replace("\\", "/")
        try:
            c = py.read_text(encoding="utf-8", errors="ignore")
            t = ast.parse(c)
        except: continue
        imps, dc, df, uc, uf = [], set(), set(), set(), set()
        for n in ast.iter_child_nodes(t):
            if isinstance(n, ast.Import):
                for a in n.names: imps.append(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module:
                imps.append(n.module.split(".")[0])
            elif isinstance(n, ast.ClassDef): dc.add(n.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): df.add(n.name)
        for n in ast.walk(t):
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name): uf.add(n.func.id)
                elif isinstance(n.func, ast.Attribute): uf.add(n.func.attr)
            elif isinstance(n, ast.Name) and n.id[0].isupper(): uc.add(n.id)
        files[rel] = dict(content=c, tokens=len(ENC.encode(c)), imps=imps, dc=dc, df=df, uc=uc, uf=uf)
    return files

def mkgraph(files, density):
    G = nx.DiGraph()
    for p in files: G.add_node(p)
    if density >= 1:  # imports
        for p, d in files.items():
            for im in d["imps"]:
                for c in files:
                    if c!=p and (c.replace("/",".").endswith(im) or im in c.split("/")[-1].replace(".py","")):
                        G.add_edge(p, c); break
    if density >= 2:  # + class refs
        cm = defaultdict(set)
        for p,d in files.items():
            for c in d["dc"]: cm[c].add(p)
        for p,d in files.items():
            for c in d["uc"]:
                for t in cm.get(c, set()):
                    if t!=p: G.add_edge(p, t); break
    if density >= 3:  # + func calls
        fm = defaultdict(set)
        for p,d in files.items():
            for f in d["df"]: fm[f].add(p)
        for p,d in files.items():
            for f in d["uf"]:
                for t in fm.get(f, set()):
                    if t!=p: G.add_edge(p, t); break
    return G

def top20(pr, files):
    sp = sorted(pr.items(), key=lambda x: x[1], reverse=True)
    n = max(1, int(len(sp)*0.20))
    return set(p for p,_ in sp[:n])

def rand20(files):
    allf = list(files.keys())
    random.shuffle(allf)
    n = max(1, int(len(allf)*0.20))
    return set(allf[:n])

def rag20(files, query):
    qw = set(w.lower() for w in query.split() if len(w)>2)
    scores = {}
    for p, d in files.items():
        cl = d["content"].lower()
        score = sum(1 for w in qw if w in cl)
        if score: scores[p] = score
    sf = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    n = max(1, int(len(files)*0.20))
    return set(p for p,_ in sf[:n])

def judge(gold, sel):
    if gold in sel: return "SUFFICIENT"
    for p in sel:
        if gold in p or p in gold: return "PARTIAL"
    return "INSUFFICIENT"

def build_ctx(files, sel, max_tok=70000):
    parts = []; total = 0
    for p in sel:
        if p in files:
            t = files[p]["tokens"]
            if total + t > max_tok: break
            parts.append(f"=== {p} ===\n{files[p]['content']}\n")
            total += t
    return "\n".join(parts), total

def run(name, files, pr):
    results = []
    for q, gold in GOLD.items():
        sel = top20(pr, files) if name=="pagerank" else (rand20(files) if name=="random" else rag20(files, q))
        verdict = judge(gold, sel)
        ctx, tok = build_ctx(files, sel)
        results.append({"query":q, "gold":gold, "verdict":verdict, "tokens":tok, "hit":gold in sel})
    return results

def main():
    print("="*70)
    print("E2E: Sparse vs Dense Graph Comparison")
    print("="*70)
    files = scan()
    print(f"Files: {len(files)}, Queries: {len(GOLD)}")

    for density, label in [(1, "Sparse (imports only)"), (3, "Dense (imports+class+func)")]:
        G = mkgraph(files, density)
        pr = nx.pagerank(G, alpha=0.85)
        print(f"\n{label}: {G.number_of_edges()} edges")

        for method in ["pagerank", "random", "rag"]:
            r = run(method, files, pr)
            suff = sum(1 for x in r if x["verdict"]=="SUFFICIENT")
            hit = sum(1 for x in r if x["hit"])
            avg_t = sum(x["tokens"] for x in r)/len(r)
            print(f"  {method:8s}: SUFF={suff:2d}  Hit@Gold={hit:2d}  AvgTok={avg_t:,.0f}")

if __name__ == "__main__":
    main()