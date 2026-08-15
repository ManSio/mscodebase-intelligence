#!/usr/bin/env python3
"""
v3 experiment: Comprehensive PageRank verification with multiple accuracy methods.

Goal: Establish a reliable pattern, not just one number.
- 50 test queries (not 10 or 30)
- 3 accuracy methods (keyword, semantic, manual)
- Multiple graph densities (import-only, AST-light, AST-full)
- Cross-validation with Smart Summary
"""

import sys
import json
import time
import ast
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


# ══════════════════════════════════════════════════════════
# GRAPH BUILDERS (3 densities)
# ══════════════════════════════════════════════════════════

def scan_files():
    """Scan all Python files with AST."""
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
        classes = set()
        functions = set()
        calls = set()
        defined_classes = set()
        defined_functions = set()

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
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
            elif isinstance(node, ast.Name) and node.id[0].isupper():
                classes.add(node.id)
            elif isinstance(node, ast.Name) and not node.id[0].isupper():
                if node.id in defined_functions:
                    functions.add(node.id)

        files[rel] = {
            "content": content,
            "tokens": len(ENC.encode(content)),
            "imports": imports,
            "defined_classes": defined_classes,
            "defined_functions": defined_functions,
            "used_classes": classes,
            "used_calls": calls,
            "lines": len(content.splitlines()),
        }

    return files


def build_graph(files, mode="full"):
    """Build graph with different densities."""
    G = nx.DiGraph()
    for path in files:
        G.add_node(path, tokens=files[path]["tokens"])

    if mode == "import_only":
        # v1: only import edges
        for path, data in files.items():
            for imp in data["imports"]:
                for candidate in files:
                    if candidate.replace("/", ".").endswith(imp) and candidate != path:
                        G.add_edge(path, candidate, type="import")
                        break

    elif mode == "ast_light":
        # imports + class references
        all_classes = defaultdict(set)
        for path, data in files.items():
            for c in data["defined_classes"]:
                all_classes[c].add(path)

        for path, data in files.items():
            for imp in data["imports"]:
                for candidate in files:
                    if candidate.replace("/", ".").endswith(imp) and candidate != path:
                        G.add_edge(path, candidate, type="import")
                        break
            for c in data["used_classes"]:
                for target in all_classes.get(c, set()):
                    if target != path:
                        G.add_edge(path, target, type="class_ref")
                        break

    elif mode == "full":
        # imports + class refs + function calls
        all_symbols = defaultdict(set)
        for path, data in files.items():
            for c in data["defined_classes"]:
                all_symbols[c].add(path)
            for f in data["defined_functions"]:
                all_symbols[f].add(path)

        for path, data in files.items():
            for imp in data["imports"]:
                for candidate in files:
                    if candidate.replace("/", ".").endswith(imp) and candidate != path:
                        G.add_edge(path, candidate, type="import")
                        break
            for call in data["used_calls"]:
                for target in all_symbols.get(call, set()):
                    if target != path:
                        G.add_edge(path, target, type="symbol_ref")
                        break

    return G


# ══════════════════════════════════════════════════════════
# 50 TEST QUERIES (real-world coding questions)
# ══════════════════════════════════════════════════════════

TEST_QUERIES = [
    # --- Where is X defined? (15) ---
    ("where is hybrid_search defined", "hybrid_search"),
    ("Searcher class implementation", "Searcher"),
    ("DebounceBatch class", "DebounceBatch"),
    ("RuntimeCoordinator", "RuntimeCoordinator"),
    ("ProjectContext snapshot", "ProjectContext"),
    ("LspClient process management", "LspClient"),
    ("ModificationGuard decorator", "modification_guard"),
    ("SymbolIndex class", "SymbolIndex"),
    ("GraphAdapterPure", "graph_adapter"),
    ("ErrorBoundary implementation", "error_boundary"),
    ("FTS5Mixin search", "fts5"),
    ("BM25 scoring algorithm", "bm25"),
    ("Reranker inference", "rerank"),
    ("EmbeddingCache", "embedding_cache"),
    ("ProjectIndexerRegistry", "ProjectIndexerRegistry"),

    # --- How does X work? (10) ---
    ("how does the search pipeline work", "search"),
    ("how is the index built", "index"),
    ("how does the rate limiter work", "rate_limit"),
    ("how does the watchdog monitor health", "watchdog"),
    ("how does error handling work", "error"),
    ("how does the MCP server start", "mcp"),
    ("how does file watching work", "watcher"),
    ("how does the installer work", "install"),
    ("how does i18n work", "i18n"),
    ("how does the sandbox execute code", "sandbox"),

    # --- Where is X used? (10) ---
    ("who calls hybrid_search", "hybrid_search"),
    ("who uses LanceDB", "lancedb"),
    ("who imports the config", "settings"),
    ("who calls the reranker", "rerank"),
    ("who uses asyncio locks", "asyncio"),
    ("who calls embedding_cache", "embedding_cache"),
    ("who uses the watchdog", "watchdog"),
    ("who calls notify_change", "notify_change"),
    ("who imports error_handler", "error_handler"),
    ("who calls search_code", "search_code"),

    # --- Architecture questions (10) ---
    ("what are the main layers of the project", "layer"),
    ("what is the entry point", "main"),
    ("what files are in core/", "core"),
    ("what is the dependency graph", "import"),
    ("what are the hotspots", "hotspot"),
    ("what tests exist", "test"),
    ("what is the project structure", "src"),
    ("what are the external dependencies", "httpx"),
    ("what database is used", "lance"),
    ("what models are loaded", "model"),

    # --- Bug-related (5) ---
    ("where could a race condition happen", "lock"),
    ("where is memory managed", "memory"),
    ("where are timeouts configured", "timeout"),
    ("where is logging configured", "logger"),
    ("where are SQL queries built", "sql"),
]


# ══════════════════════════════════════════════════════════
# ACCURACY METHODS
# ══════════════════════════════════════════════════════════

def accuracy_keyword(top_paths, files, keyword):
    """Method 1: keyword appears in any top file."""
    for path in top_paths:
        if path in files and keyword.lower() in files[path]["content"].lower():
            return True
    return False


def accuracy_symbol(top_paths, files, keyword):
    """Method 2: keyword matches a defined symbol in top files."""
    for path in top_paths:
        if path in files:
            data = files[path]
            kw = keyword.lower()
            if any(kw in c.lower() for c in data["defined_classes"]):
                return True
            if any(kw in f.lower() for f in data["defined_functions"]):
                return True
            # Also check filename
            fname = path.split("/")[-1].lower().replace(".py", "")
            if kw in fname:
                return True
    return False


def accuracy_semantic(top_paths, files, query_words):
    """Method 3: multiple query words match content (stricter)."""
    matched_files = 0
    for path in top_paths:
        if path in files:
            content_lower = files[path]["content"].lower()
            matches = sum(1 for w in query_words if w in content_lower)
            if matches >= 2:
                matched_files += 1
    return matched_files > 0


# ══════════════════════════════════════════════════════════
# SMART SUMMARY
# ══════════════════════════════════════════════════════════

def build_smart_summary(files, pr_scores):
    ranked = sorted(pr_scores.items(), key=lambda x: x[1], reverse=True)
    summary_lines = []
    for path, score in ranked[:30]:
        data = files[path]
        syms = list(data["defined_classes"] | data["defined_functions"])[:6]
        fname = path.split("/")[-1]
        summary_lines.append(f"{fname} [{score:.4f}] {', '.join(syms)}")
    summary_text = "\n".join(summary_lines)
    summary_tokens = len(ENC.encode(summary_text))
    return summary_text, summary_tokens


def query_summary_accuracy(summary_text, keyword):
    """Check if keyword appears in summary."""
    return keyword.lower() in summary_text.lower()


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("EXPERIMENT v3: Comprehensive PageRank Verification")
    print("=" * 70)
    print(f"Project: {PROJECT}")
    print(f"Queries: {len(TEST_QUERIES)}")
    print(f"Accuracy methods: keyword, symbol, semantic")
    print(f"Graph densities: import_only, ast_light, ast_full")
    print()

    # Scan files
    files = scan_files()
    total_tokens = sum(d["tokens"] for d in files.values())
    print(f"Files: {len(files)}, Total tokens: {total_tokens:,}")
    print()

    all_results = {}

    for mode in ["import_only", "ast_light", "ast_full"]:
        print(f"{'='*70}")
        print(f"GRAPH: {mode.upper()}")
        print(f"{'='*70}")

        G = build_graph(files, mode)
        print(f"  Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")

        pr = nx.pagerank(G, alpha=0.85)
        sorted_pr = sorted(pr.items(), key=lambda x: x[1], reverse=True)

        # Top 5
        print(f"  Top 5:")
        for path, score in sorted_pr[:5]:
            tokens = files.get(path, {}).get("tokens", 0)
            print(f"    {score:.4f}  {tokens:>6,} tok  {path.split('/')[-1]}")
        print()

        # Smart Summary
        summary_text, summary_tokens = build_smart_summary(files, pr)

        # Test each percentage
        mode_results = {}
        for top_pct in [10, 20, 30, 50]:
            n = max(1, int(len(sorted_pr) * top_pct / 100))
            top_paths = [p for p, _ in sorted_pr[:n]]
            top_tokens = sum(files.get(p, {}).get("tokens", 0) for p in top_paths)
            savings = (total_tokens - top_tokens) / total_tokens * 100

            acc_keyword = 0
            acc_symbol = 0
            acc_semantic = 0

            for query, keyword in TEST_QUERIES:
                words = [w.lower() for w in query.split() if len(w) > 2]
                if accuracy_keyword(top_paths, files, keyword):
                    acc_keyword += 1
                if accuracy_symbol(top_paths, files, keyword):
                    acc_symbol += 1
                if accuracy_semantic(top_paths, files, words):
                    acc_semantic += 1

            acc_keyword = acc_keyword / len(TEST_QUERIES) * 100
            acc_symbol = acc_symbol / len(TEST_QUERIES) * 100
            acc_semantic = acc_semantic / len(TEST_QUERIES) * 100

            mode_results[top_pct] = {
                "files": n,
                "tokens": top_tokens,
                "savings": round(savings, 1),
                "acc_keyword": round(acc_keyword, 1),
                "acc_symbol": round(acc_symbol, 1),
                "acc_semantic": round(acc_semantic, 1),
            }

            print(f"  Top {top_pct:3d}%: {n:3d} files, {top_tokens:>10,} tokens, "
                  f"savings {savings:>+6.1f}%")
            print(f"           keyword={acc_keyword:.0f}%  symbol={acc_symbol:.0f}%  "
                  f"semantic={acc_semantic:.0f}%")

        # Smart Summary accuracy
        ss_hits = 0
        for query, keyword in TEST_QUERIES:
            if query_summary_accuracy(summary_text, keyword):
                ss_hits += 1
        ss_accuracy = ss_hits / len(TEST_QUERIES) * 100

        print(f"\n  Smart Summary: {summary_tokens:,} tokens, "
              f"savings {(total_tokens-summary_tokens)/total_tokens*100:+.1f}%, "
              f"accuracy {ss_accuracy:.0f}%")
        print()

        all_results[mode] = {
            "edges": G.number_of_edges(),
            "percentages": mode_results,
            "smart_summary": {
                "tokens": summary_tokens,
                "savings": round((total_tokens-summary_tokens)/total_tokens*100, 1),
                "accuracy": round(ss_accuracy, 1),
            },
            "top5": [(p, round(s, 4), files.get(p, {}).get("tokens", 0))
                     for p, s in sorted_pr[:5]],
        }

    # ══════════════════════════════════════════════════════
    # FINAL COMPARISON TABLE
    # ══════════════════════════════════════════════════════
    print("=" * 70)
    print("FINAL COMPARISON (Top 20% — the practical sweet spot)")
    print("=" * 70)
    print(f"{'Graph':<15} {'Edges':>6} {'Tokens':>10} {'Savings':>8} "
          f"{'Keyword':>8} {'Symbol':>8} {'Semantic':>8}")
    print("-" * 70)

    for mode in ["import_only", "ast_light", "ast_full"]:
        r = all_results[mode]
        p = r["percentages"][20]
        print(f"  {mode:<13} {r['edges']:>6} {p['tokens']:>10,} "
              f"{p['savings']:>+7.1f}% {p['acc_keyword']:>7.0f}% "
              f"{p['acc_symbol']:>7.0f}% {p['acc_semantic']:>7.0f}%")

    ss = all_results["ast_full"]["smart_summary"]
    print(f"  {'Smart Summary':<13} {'—':>6} {ss['tokens']:>10,} "
          f"{ss['savings']:>+7.1f}% {ss['accuracy']:>7.0f}% {'—':>8} {'—':>8}")
    print(f"  {'Full context':<13} {'—':>6} {total_tokens:>10,} "
          f"{'baseline':>8} {'100%':>8} {'100%':>8} {'100%':>8}")

    # Pattern detection
    print()
    print("=" * 70)
    print("PATTERN ANALYSIS")
    print("=" * 70)

    # Does accuracy improve with graph density?
    import_acc = all_results["import_only"]["percentages"][20]["acc_keyword"]
    full_acc = all_results["ast_full"]["percentages"][20]["acc_keyword"]
    print(f"  Graph density effect (Top 20%, keyword accuracy):")
    print(f"    import_only: {import_acc:.0f}%")
    print(f"    ast_light:   {all_results['ast_light']['percentages'][20]['acc_keyword']:.0f}%")
    print(f"    ast_full:    {full_acc:.0f}%")
    print(f"    Delta:       {full_acc - import_acc:+.0f} percentage points")
    print()

    # Does Top 20% actually save tokens?
    for mode in ["import_only", "ast_light", "ast_full"]:
        p10 = all_results[mode]["percentages"][10]["savings"]
        p20 = all_results[mode]["percentages"][20]["savings"]
        p50 = all_results[mode]["percentages"][50]["savings"]
        print(f"  {mode}: Top 10%={p10:+.1f}%  Top 20%={p20:+.1f}%  Top 50%={p50:+.1f}%")

    # Save
    output = {
        "project": str(PROJECT),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": len(files),
        "total_tokens": total_tokens,
        "queries": len(TEST_QUERIES),
        "results": all_results,
    }
    out_path = PROJECT / "experiments" / "v3_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nResults: {out_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
