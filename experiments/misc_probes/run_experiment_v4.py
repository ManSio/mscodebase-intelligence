#!/usr/bin/env python3
"""
v4: Symbol-level PageRank -> aggregate back to files.
Tests the confounding variable: is it density or granularity?
"""

import sys, json, time, ast
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict

try:
    import networkx as nx
    import tiktoken
except ImportError:
    print("pip install networkx tiktoken")
    sys.exit(1)

PROJECT = Path(r"D:\Project\MSCodeBase")
SRC_DIR = PROJECT / "src"
ENC = tiktoken.get_encoding("cl100k_base")


def scan_files():
    files = {}
    for py in sorted(SRC_DIR.rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        rel = str(py.relative_to(PROJECT)).replace("\\", "/")
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)
        except Exception:
            continue

        imports = []
        defined_classes = set()
        defined_functions = set()
        used_classes = set()
        used_calls = set()

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module.split(".")[0])
            elif isinstance(node, ast.ClassDef):
                defined_classes.add(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined_functions.add(node.name)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    used_calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    used_calls.add(node.func.attr)
            elif isinstance(node, ast.Name) and node.id[0].isupper():
                used_classes.add(node.id)

        files[rel] = {
            "content": content,
            "tokens": len(ENC.encode(content)),
            "imports": imports,
            "defined_classes": defined_classes,
            "defined_functions": defined_functions,
            "used_classes": used_classes,
            "used_calls": used_calls,
        }
    return files


def build_symbol_graph(files):
    """Symbol-level graph: nodes = symbols (file::symbol), edges = calls/refs."""
    G = nx.DiGraph()

    # Build symbol registry
    symbol_to_file = {}  # symbol_name -> file_path
    symbol_nodes = {}    # "file::symbol" -> file_path

    for path, data in files.items():
        for c in data["defined_classes"]:
            node_id = f"{path}::{c}"
            G.add_node(node_id, file=path, kind="class", name=c)
            symbol_nodes[node_id] = path
            symbol_to_file[c] = path
        for f in data["defined_functions"]:
            node_id = f"{path}::{f}"
            G.add_node(node_id, file=path, kind="function", name=f)
            symbol_nodes[node_id] = path
            symbol_to_file[f] = path

    # Also add file-level nodes for imports
    for path in files:
        G.add_node(f"__file__{path}", file=path, kind="file", name=path.split("/")[-1])
        symbol_nodes[f"__file__{path}"] = path

    # Import edges (file → file)
    for path, data in files.items():
        for imp in data["imports"]:
            for candidate in files:
                if candidate.replace("/", ".").endswith(imp) and candidate != path:
                    G.add_edge(f"__file__{path}", f"__file__{candidate}", type="import")
                    break

    # Symbol reference edges (caller → callee)
    for path, data in files.items():
        for call in data["used_calls"]:
            if call in symbol_to_file:
                target_file = symbol_to_file[call]
                # file → symbol
                G.add_edge(f"__file__{path}", f"{target_file}::{call}", type="calls")

        for cls in data["used_classes"]:
            if cls in symbol_to_file:
                target_file = symbol_to_file[cls]
                G.add_edge(f"__file__{path}", f"{target_file}::{cls}", type="refs")

    # Symbol → file membership edges (bidirectional)
    for node_id, file_path in symbol_nodes.items():
        if not node_id.startswith("__file__"):
            G.add_edge(node_id, f"__file__{file_path}", type="defined_in")
            G.add_edge(f"__file__{file_path}", node_id, type="defines")

    return G, symbol_nodes


def aggregate_to_files(pr_scores, symbol_nodes):
    """Aggregate symbol-level PageRank back to file level."""
    file_scores = defaultdict(float)
    for node, score in pr_scores.items():
        if node in symbol_nodes:
            file_scores[symbol_nodes[node]] += score
    return dict(file_scores)


def accuracy_check(top_files, files, keyword):
    for path in top_files:
        if path in files and keyword.lower() in files[path]["content"].lower():
            return True
    return False


TEST_QUERIES = [
    ("hybrid_search defined", "hybrid_search"),
    ("Searcher class", "Searcher"),
    ("DebounceBatch", "DebounceBatch"),
    ("RuntimeCoordinator", "RuntimeCoordinator"),
    ("ProjectContext", "ProjectContext"),
    ("LspClient", "LspClient"),
    ("ModificationGuard", "modification_guard"),
    ("SymbolIndex", "SymbolIndex"),
    ("GraphAdapterPure", "graph_adapter"),
    ("ErrorBoundary", "error_boundary"),
    ("FTS5Mixin", "fts5"),
    ("BM25 scoring", "bm25"),
    ("Reranker inference", "rerank"),
    ("EmbeddingCache", "embedding_cache"),
    ("ProjectIndexerRegistry", "ProjectIndexerRegistry"),
    ("how does search pipeline work", "search"),
    ("how is the index built", "index"),
    ("rate limiter", "rate_limit"),
    ("watchdog monitor", "watchdog"),
    ("error handling", "error"),
    ("MCP server start", "mcp"),
    ("file watching", "watcher"),
    ("installer", "install"),
    ("i18n translation", "i18n"),
    ("sandbox execution", "sandbox"),
    ("who calls hybrid_search", "hybrid_search"),
    ("who uses LanceDB", "lancedb"),
    ("who imports config", "settings"),
    ("who calls reranker", "rerank"),
    ("asyncio locks", "asyncio"),
    ("embedding_cache usage", "embedding_cache"),
    ("watchdog usage", "watchdog"),
    ("notify_change callers", "notify_change"),
    ("error_handler imports", "error_handler"),
    ("search_code usage", "search_code"),
    ("main layers", "layer"),
    ("entry point", "main"),
    ("core files", "core"),
    ("dependency graph", "import"),
    ("hotspots", "hotspot"),
    ("test files", "test"),
    ("project structure", "src"),
    ("external dependencies", "httpx"),
    ("database", "lance"),
    ("models loaded", "model"),
    ("race condition", "lock"),
    ("memory management", "memory"),
    ("timeouts", "timeout"),
    ("logging config", "logger"),
    ("SQL queries", "sql"),
]


def main():
    print("=" * 70)
    print("EXPERIMENT v4: Symbol PageRank -> Aggregate to Files")
    print("Testing: is it density or granularity?")
    print("=" * 70)

    files = scan_files()
    total_tokens = sum(d["tokens"] for d in files.values())
    print(f"Files: {len(files)}, Tokens: {total_tokens:,}")

    # ── Build symbol-level graph ──
    G, symbol_nodes = build_symbol_graph(files)
    sym_count = sum(1 for n in G.nodes if not n.startswith("__file__"))
    file_count = sum(1 for n in G.nodes if n.startswith("__file__"))
    print(f"Symbol graph: {G.number_of_nodes()} nodes ({sym_count} symbols + {file_count} files), "
          f"{G.number_of_edges()} edges")

    # ── Run PageRank on symbol graph ──
    print("\nRunning PageRank on symbol graph...")
    pr = nx.pagerank(G, alpha=0.85)

    # ── Aggregate to files ──
    file_pr = aggregate_to_files(pr, symbol_nodes)
    sorted_files = sorted(file_pr.items(), key=lambda x: x[1], reverse=True)

    print("\nTop 10 files by aggregated PageRank:")
    for path, score in sorted_files[:10]:
        tokens = files.get(path, {}).get("tokens", 0)
        print(f"  {score:.4f}  {tokens:>6,} tok  {path.split('/')[-1]}")

    # ── Measure accuracy ──
    print("\n--- Symbol PageRank (aggregated to files) ---")
    for top_pct in [10, 20, 50]:
        n = max(1, int(len(sorted_files) * top_pct / 100))
        top_paths = [p for p, _ in sorted_files[:n]]
        top_tokens = sum(files.get(p, {}).get("tokens", 0) for p in top_paths)
        savings = (total_tokens - top_tokens) / total_tokens * 100

        hits = sum(1 for q, kw in TEST_QUERIES if accuracy_check(top_paths, files, kw))
        acc = hits / len(TEST_QUERIES) * 100

        print(f"  Top {top_pct:3d}%: {n:3d} files, {top_tokens:>10,} tokens, "
              f"savings {savings:>+6.1f}%, accuracy {acc:.0f}%")

    # ── Compare: file-level ast_light vs symbol-level ──
    print("\n" + "=" * 70)
    print("COMPARISON: File-level vs Symbol-level PageRank (Top 20%)")
    print("=" * 70)

    # File-level ast_light (from v3: 168 edges, 88% accuracy)
    print(f"  {'Method':<35} {'Edges':>6} {'Tokens':>10} {'Savings':>8} {'Accuracy':>8}")
    print("-" * 70)
    print(f"  {'File-level ast_light (v3)':<35} {'168':>6} {'125,642':>10} {'+69.0%':>8} {'88%':>8}")

    # Symbol-level (current)
    n20 = max(1, int(len(sorted_files) * 20 / 100))
    top20_sym = [p for p, _ in sorted_files[:n20]]
    tok20_sym = sum(files.get(p, {}).get("tokens", 0) for p in top20_sym)
    sav20_sym = (total_tokens - tok20_sym) / total_tokens * 100
    acc20_sym = sum(1 for q, kw in TEST_QUERIES if accuracy_check(top20_sym, files, kw)) / len(TEST_QUERIES) * 100

    print(f"  {'Symbol→File aggregated':<35} {G.number_of_edges():>6} {tok20_sym:>10,} "
          f"{sav20_sym:>+7.1f}% {acc20_sym:>7.0f}%")
    print(f"  {'Full context':<35} {'—':>6} {total_tokens:>10,} {'baseline':>8} {'100%':>8}")

    # ── Verdict ──
    print("\n" + "=" * 70)
    print("VERDICT: Density vs Granularity")
    print("=" * 70)
    file_acc = 88  # from v3 ast_light
    sym_acc = acc20_sym
    delta = sym_acc - file_acc

    if abs(delta) < 5:
        print(f"  Both approaches give similar accuracy ({file_acc:.0f}% vs {sym_acc:.0f}%)")
        print(f"  → DENSITY is the main driver, not granularity")
        print(f"  → The +12pp improvement from v3 is real and generalizes")
    elif delta > 5:
        print(f"  Symbol-level ({sym_acc:.0f}%) beats file-level ({file_acc:.0f}%) by {delta:+.0f}pp")
        print(f"  → GRANULARITY contributes significantly")
        print(f"  → Some of the +12pp was from granularity, not just density")
    else:
        print(f"  File-level ({file_acc:.0f}%) beats symbol-level ({sym_acc:.0f}%) by {-delta:+.0f}pp")
        print(f"  → Symbol-level aggregation loses information")
        print(f"  → File-level dense graph is sufficient")

    # Save
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol_graph": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges()},
        "file_level_top20": {"savings": 69.0, "accuracy": 88},
        "symbol_level_top20": {"savings": round(sav20_sym, 1), "accuracy": round(acc20_sym, 1)},
        "verdict": "density" if abs(delta) < 5 else ("granularity" if delta > 5 else "file_level_sufficient"),
    }
    out_path = PROJECT / "experiments" / "v4_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults: {out_path}")


if __name__ == "__main__":
    main()
