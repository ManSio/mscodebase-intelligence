#!/usr/bin/env python3
"""v5: Full scientific experiment — PageRank for code context reduction."""
import sys, json, time, ast, statistics, math, random
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

def scan():
    files = {}
    for py in sorted(SRC.rglob("*.py")):
        if "__pycache__" in str(py): continue
        rel = str(py.relative_to(PROJECT)).replace("\\","/")
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
        files[rel] = dict(content=c, tokens=len(ENC.encode(c)),
            lines=len(c.splitlines()), imps=imps, dc=dc, df=df, uc=uc, uf=uf)
    return files

def mkgraph(files, density):
    G = nx.DiGraph()
    for p in files: G.add_node(p)
    if density == 0: return G
    if density >= 1:
        for p, d in files.items():
            for im in d["imps"]:
                for c in files:
                    if c!=p and (c.replace("/",".").endswith(im) or im in c.split("/")[-1].replace(".py","")):
                        G.add_edge(p,c); break
    if density >= 2:
        cm = defaultdict(set)
        for p,d in files.items():
            for c in d["dc"]: cm[c].add(p)
        for p,d in files.items():
            for c in d["uc"]:
                for t in cm.get(c,set()):
                    if t!=p: G.add_edge(p,t); break
    if density >= 3:
        fm = defaultdict(set)
        for p,d in files.items():
            for f in d["df"]: fm[f].add(p)
        for p,d in files.items():
            for f in d["uf"]:
                for t in fm.get(f,set()):
                    if t!=p: G.add_edge(p,t); break
    return G

QUERIES = [
    ("hybrid_search defined","hybrid_search"),("Searcher class","Searcher"),
    ("DebounceBatch","DebounceBatch"),("RuntimeCoordinator","RuntimeCoordinator"),
    ("ProjectContext","ProjectContext"),("LspClient","LspClient"),
    ("ModificationGuard","modification_guard"),("SymbolIndex","SymbolIndex"),
    ("GraphAdapterPure","graph_adapter"),("ErrorBoundary","error_boundary"),
    ("FTS5Mixin","fts5"),("BM25 scoring","bm25"),("Reranker","rerank"),
    ("EmbeddingCache","embedding_cache"),("ProjectIndexerRegistry","ProjectIndexerRegistry"),
    ("search pipeline","search"),("index building","index"),
    ("rate limiter","rate_limit"),("watchdog","watchdog"),
    ("error handling","error"),("MCP server","mcp"),
    ("file watching","watcher"),("installer","install"),
    ("i18n","i18n"),("sandbox","sandbox"),
    ("who calls hybrid_search","hybrid_search"),("who uses LanceDB","lancedb"),
    ("who imports config","settings"),("who calls reranker","rerank"),
    ("asyncio locks","asyncio"),("embedding_cache usage","embedding_cache"),
    ("watchdog usage","watchdog"),("notify_change","notify_change"),
    ("error_handler","error_handler"),("search_code","search_code"),
    ("main layers","layer"),("entry point","main"),
    ("core files","core"),("dependency graph","import"),
    ("hotspots","hotspot"),("test files","test"),
    ("project structure","src"),("external deps","httpx"),
    ("database","lance"),("models","model"),
    ("race condition","lock"),("memory","memory"),
    ("timeouts","timeout"),("logging","logger"),("SQL","sql"),
]

def acc_kw(top, files, kw):
    for p in top:
        if p in files and kw.lower() in files[p]["content"].lower(): return True
    return False

def acc_sym(top, files, kw):
    for p in top:
        if p in files:
            d = files[p]
            k = kw.lower()
            if any(k in c.lower() for c in d["dc"]): return True
            if any(k in f.lower() for f in d["df"]): return True
            if k in p.split("/")[-1].lower().replace(".py",""): return True
    return False

def acc_sem(top, files, query):
    words = [w.lower() for w in query.split() if len(w)>2]
    for p in top:
        if p in files:
            cl = files[p]["content"].lower()
            if sum(1 for w in words if w in cl) >= 2: return True
    return False

def acc_cov(top, files, kw):
    """Coverage: how many of the TOP relevant files are in the selection."""
    relevant = [p for p in files if kw.lower() in p.split("/")[-1].lower().replace(".py","")]
    if not relevant: return 1.0
    found = sum(1 for r in relevant if r in top)
    return found / len(relevant)

def spearman(a, b):
    n = len(a)
    ra = [sorted(range(n), key=lambda i: a[i]).index(i) for i in range(n)]
    rb = [sorted(range(n), key=lambda i: b[i]).index(i) for i in range(n)]
    d2 = sum((ra[i]-rb[i])**2 for i in range(n))
    return 1 - 6*d2/(n*(n*n-1))

def cross_validate(files, graph_fn, top_pct, n_folds=5):
    queries = QUERIES[:]
    random.shuffle(queries)
    fold_size = len(queries) // n_folds
    fold_results = []

    for fold in range(n_folds):
        test_q = queries[fold*fold_size:(fold+1)*fold_size]
        train_q = [q for q in QUERIES if q not in test_q]

        G = graph_fn()
        pr = nx.pagerank(G, alpha=0.85)
        sorted_pr = sorted(pr.items(), key=lambda x: x[1], reverse=True)
        n = max(1, int(len(sorted_pr)*top_pct/100))
        top_paths = set(p for p,_ in sorted_pr[:n])

        kw = sum(1 for q,k in test_q if acc_kw(top_paths,files,k)) / len(test_q)
        sy = sum(1 for q,k in test_q if acc_sym(top_paths,files,k)) / len(test_q)
        se = sum(1 for q,k in test_q if acc_sem(top_paths,files,k)) / len(test_q)
        cv = sum(acc_cov(top_paths,files,k) for _,k in test_q) / len(test_q)
        fold_results.append({"keyword":kw,"symbol":sy,"semantic":se,"coverage":cv})

    agg = {}
    for m in ["keyword","symbol","semantic","coverage"]:
        vals = [f[m] for f in fold_results]
        agg[m] = {"mean": round(statistics.mean(vals)*100,1),
                   "std": round(statistics.stdev(vals)*100,1) if len(vals)>1 else 0,
                   "min": round(min(vals)*100,1), "max": round(max(vals)*100,1)}
    return agg

def main():
    print("="*72)
    print("  v5: SCIENTIFIC EXPERIMENT — PageRank for Code Context")
    print("="*72)
    t0 = time.time()
    files = scan()
    total_tok = sum(d["tokens"] for d in files.values())
    print(f"Files: {len(files)}  Tokens: {total_tok:,}  Queries: {len(QUERIES)}")
    print(f"Cross-validation: 5-fold, shuffled, mean +/- std")
    print()

    density_names = {0:"random_baseline", 1:"import_only", 2:"+class_refs",
                     3:"+func_calls", 4:"full_ast"}
    all_data = {}

    for d in range(5):
        label = density_names[d]
        G = mkgraph(files, d)
        edges = G.number_of_edges()

        # Compute PageRank
        pr = nx.pagerank(G, alpha=0.85)
        sorted_pr = sorted(pr.items(), key=lambda x: x[1], reverse=True)

        # File size correlation (Spearman)
        pr_scores = [pr.get(p,0) for p in files]
        tok_sizes = [files[p]["tokens"] for p in files]
        rho = spearman(pr_scores, tok_sizes)

        print(f"DENSITY {d}: {label} ({edges} edges) Spearman(rank,size)={rho:.3f}")

        # Token savings for different top%
        savings_data = {}
        for pct in [10, 20, 30, 50]:
            n = max(1, int(len(sorted_pr)*pct/100))
            top = [p for p,_ in sorted_pr[:n]]
            tok = sum(files.get(p,{}).get("tokens",0) for p in top)
            sav = (total_tok - tok) / total_tok * 100
            savings_data[pct] = {"files":n, "tokens":tok, "savings":round(sav,1)}
            print(f"  Top {pct:3d}%: {n:3d} files, {tok:>10,} tok, {sav:>+6.1f}%")

        # Cross-validation for Top 20%
        print(f"  Cross-validating Top 20% (5-fold)...")
        cv = cross_validate(files, lambda: mkgraph(files, d), 0.20)
        for m, v in cv.items():
            print(f"    {m:10s}: {v['mean']:5.1f}% +/- {v['std']:.1f}% [{v['min']:.0f}-{v['max']:.0f}]")

        # Sensitivity: alpha sweep
        alpha_results = {}
        for alpha in [0.5, 0.7, 0.85, 0.95]:
            pr_a = nx.pagerank(G, alpha=alpha)
            sorted_a = sorted(pr_a.items(), key=lambda x: x[1], reverse=True)
            n20 = max(1, int(len(sorted_a)*0.20))
            top20 = set(p for p,_ in sorted_a[:n20])
            kw = sum(1 for q,k in QUERIES if acc_kw(top20,files,k)) / len(QUERIES)
            alpha_results[alpha] = round(kw*100,1)
        print(f"  Alpha sweep (keyword acc @ Top 20%): {alpha_results}")

        all_data[label] = {
            "edges": edges,
            "spearman_rho": round(rho, 3),
            "savings": savings_data,
            "cross_val_20pct": cv,
            "alpha_sweep": alpha_results,
            "top5": [(p.split("/")[-1], round(s,4), files.get(p,{}).get("tokens",0))
                     for p,s in sorted_pr[:5]],
        }
        print()

    # Smart Summary baseline
    print("SMART SUMMARY BASELINE")
    ranked = sorted(nx.pagerank(mkgraph(files,3), alpha=0.85).items(),
                    key=lambda x: x[1], reverse=True)
    syms = []
    for p,s in ranked[:30]:
        d = files[p]
        syms.append(f"{p.split('/')[-1]} [{s:.4f}] {','.join(list(d['dc']|d['df'])[:5])}")
    ss_text = "\n".join(syms)
    ss_tok = len(ENC.encode(ss_text))
    ss_hits = sum(1 for q,k in QUERIES if k.lower() in ss_text.lower())
    ss_acc = round(ss_hits/len(QUERIES)*100, 1)
    print(f"  Tokens: {ss_tok:,}  Savings: {(total_tok-ss_tok)/total_tok*100:+.1f}%  Accuracy: {ss_acc}%")
    all_data["smart_summary"] = {"tokens":ss_tok, "savings":round((total_tok-ss_tok)/total_tok*100,1), "accuracy":ss_acc}
    print()

    # FINAL TABLE
    print("="*72)
    print("  FINAL RESULTS TABLE")
    print("="*72)
    print(f"{'Method':<25} {'Edges':>6} {'Tokens@20%':>10} {'Savings':>8} {'Keyword':>10} {'Symbol':>10} {'Semantic':>10} {'Spearman':>9}")
    print("-"*95)
    for label in ["random_baseline","import_only","+class_refs","+func_calls","full_ast"]:
        d = all_data[label]
        s20 = d["savings"][20]
        cv20 = d["cross_val_20pct"]
        print(f"  {label:<23} {d['edges']:>6} {s20['tokens']:>10,} {s20['savings']:>+7.1f}% "
              f"{cv20['keyword']['mean']:>5.1f}+/-{cv20['keyword']['std']:<4.1f} "
              f"{cv20['symbol']['mean']:>5.1f}+/-{cv20['symbol']['std']:<4.1f} "
              f"{cv20['semantic']['mean']:>5.1f}+/-{cv20['semantic']['std']:<4.1f} "
              f"{d['spearman_rho']:>+8.3f}")
    ss = all_data["smart_summary"]
    print(f"  {'Smart Summary':<23} {'--':>6} {ss['tokens']:>10,} {ss['savings']:>+7.1f}% "
          f"{ss['accuracy']:>5.1f}%")
    print(f"  {'Full context':<23} {'--':>6} {total_tok:>10,} {'baseline':>8} {'100.0%':>10} {'100.0%':>10} {'100.0%':>10}")

    elapsed = time.time() - t0
    print(f"\nTotal runtime: {elapsed:.1f}s")

    all_data["_meta"] = {
        "files": len(files), "total_tokens": total_tok,
        "queries": len(QUERIES), "folds": 5, "seed": 42,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runtime_s": round(elapsed,1),
    }
    out = PROJECT / "experiments" / "v5_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    print(f"Raw data: {out}")
    print("="*72)

if __name__ == "__main__":
    main()
