#!/usr/bin/env python3
"""run_experiment_pagerank.py — Measure PageRank token savings on a real codebase.

Reproduces the experiment from the blog post:
"I Measured PageRank Token Savings on a Real Codebase"

Usage:
    python experiments/run_experiment_pagerank.py [project_root]

Requirements:
    pip install networkx tiktoken

Output:
    - Token counts for Top 10%, 20%, 50%, 100% by PageRank
    - Accuracy measurement on 10 test queries
    - CSV file with detailed results
"""

import sys
import csv
import json
import time
from pathlib import Path
from collections import defaultdict

try:
    import networkx as nx
except ImportError:
    print("ERROR: networkx not installed. Run: pip install networkx")
    sys.exit(1)

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False
    print("WARNING: tiktoken not installed. Using word count as token estimate.")
    print("For accurate results: pip install tiktoken")


def build_call_graph(project_root: Path):
    """Build a call graph from Python files using simple import/call analysis."""
    G = nx.DiGraph()
    
    py_files = list(project_root.rglob("*.py"))
    print(f"Found {len(py_files)} Python files")
    
    for f in py_files:
        # Skip hidden dirs, __pycache__, etc.
        parts = f.relative_to(project_root).parts
        if any(p.startswith(".") or p == "__pycache__" or p == "node_modules" for p in parts):
            continue
        
        node_id = str(f.relative_to(project_root))
        G.add_node(node_id, path=str(f), size=f.stat().st_size)
        
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            
            # Extract imports
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("from ") or line.startswith("import "):
                    # Simple heuristic: extract module name
                    if "from " in line:
                        module = line.split("from ")[1].split(" import")[0].strip()
                    else:
                        module = line.split("import ")[1].split(" as")[0].split(",")[0].strip()
                    
                    # Try to resolve to a file
                    if module.startswith("."):
                        continue  # Relative import, skip for now
                    
                    # Simple resolution: convert dots to path separators
                    module_path = module.replace(".", "/")
                    for candidate in [f"{module_path}.py", f"{module_path}/__init__.py"]:
                        candidate_path = project_root / candidate
                        if candidate_path.exists():
                            target_id = str(candidate_path.relative_to(project_root))
                            if target_id in G:
                                G.add_edge(node_id, target_id, type="import")
                            break
        except Exception:
            continue
    
    print(f"Built graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken or word count fallback."""
    if HAS_TIKTOKEN:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    else:
        return len(text.split())


def measure_token_savings(G: nx.DiGraph, project_root: Path):
    """Measure token savings for different PageRank selections."""
    print("\nRunning PageRank...")
    pr = nx.pagerank(G, alpha=0.85)
    
    # Sort by importance
    sorted_nodes = sorted(pr.items(), key=lambda x: x[1], reverse=True)
    
    # Read all files and count tokens
    print("Counting tokens...")
    file_tokens = {}
    for node_id, _ in sorted_nodes:
        fpath = project_root / node_id
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                file_tokens[node_id] = count_tokens(content)
            except Exception:
                file_tokens[node_id] = 0
    
    total_tokens = sum(file_tokens.values())
    total_files = len(sorted_nodes)
    
    print(f"Total: {total_files} files, {total_tokens:,} tokens")
    
    # Measure savings for different selections
    results = []
    for top_pct in [10, 20, 50, 100]:
        n = max(1, int(total_files * top_pct / 100))
        top_nodes = [node for node, _ in sorted_nodes[:n]]
        top_tokens = sum(file_tokens.get(node, 0) for node in top_nodes)
        savings = (total_tokens - top_tokens) / total_tokens * 100 if total_tokens > 0 else 0
        
        results.append({
            "top_pct": top_pct,
            "files": n,
            "tokens": top_tokens,
            "savings_pct": savings,
            "pagerank_top5": [(node, pr[node]) for node, _ in sorted_nodes[:5]],
        })
        
        print(f"  Top {top_pct:3d}%: {n:3d} files, {top_tokens:>10,} tokens, {savings:>+6.1f}% savings")
    
    return results, sorted_nodes, file_tokens, pr


def measure_accuracy(results, sorted_nodes, file_tokens, project_root):
    """Measure accuracy with 10 test queries (placeholder - customize for your project)."""
    # These are example queries - replace with queries relevant to your project
    test_queries = [
        "search code implementation",
        "rate limiter debounce",
        "error handling boundary",
        "LanceDB vector database",
        "OpenVINO embed inference",
        "asyncio event loop",
        "file guard indexer",
        "MCP tool registration",
        "project context snapshot",
        "intelligence layer ADR",
    ]
    
    print("\nMeasuring accuracy...")
    accuracy_results = []
    
    for query in test_queries:
        # Simple keyword-based relevance check
        query_words = set(query.lower().split())
        
        for top_pct in [10, 20, 50, 100]:
            n = max(1, int(len(results[0]["pagerank_top5"]) * top_pct / 100))
            # This is a simplified check - in production you'd use semantic search
            relevant_found = 0
            total_relevant = 3  # Assume 3 relevant files per query
            
            # Check if any top files contain query keywords
            for node, _ in results[0]["pagerank_top5"][:n]:
                try:
                    content = (project_root / node).read_text(encoding="utf-8", errors="ignore").lower()
                    if any(word in content for word in query_words):
                        relevant_found += 1
                except Exception:
                    pass
            
            accuracy = min(relevant_found / total_relevant * 100, 100) if total_relevant > 0 else 0
            accuracy_results.append({
                "query": query,
                "top_pct": top_pct,
                "accuracy": accuracy,
            })
    
    # Aggregate by top_pct
    aggregated = {}
    for ar in accuracy_results:
        pct = ar["top_pct"]
        if pct not in aggregated:
            aggregated[pct] = []
        aggregated[pct].append(ar["accuracy"])
    
    print("\nAccuracy by selection:")
    for pct in sorted(aggregated.keys()):
        avg_acc = sum(aggregated[pct]) / len(aggregated[pct])
        print(f"  Top {pct:3d}%: {avg_acc:.1f}% accuracy")
    
    return accuracy_results


def main():
    # Get project root from args or use current directory
    if len(sys.argv) > 1:
        project_root = Path(sys.argv[1])
    else:
        project_root = Path.cwd()
    
    print(f"Project: {project_root}")
    print(f"{'='*70}")
    
    # Build graph
    G = build_call_graph(project_root)
    
    # Measure token savings
    results, sorted_nodes, file_tokens, pr = measure_token_savings(G, project_root)
    
    # Measure accuracy
    accuracy_results = measure_accuracy(results, sorted_nodes, file_tokens, project_root)
    
    # Save results
    output_dir = Path("experiments")
    output_dir.mkdir(exist_ok=True)
    
    # Save summary
    summary_path = output_dir / "pagerank_results.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "project": str(project_root),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "graph_stats": {
                "nodes": G.number_of_nodes(),
                "edges": G.number_of_edges(),
            },
            "token_savings": results,
            "accuracy": accuracy_results,
        }, f, indent=2)
    
    print(f"\nResults saved to {summary_path}")
    
    # Save CSV
    csv_path = output_dir / "pagerank_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["top_pct", "files", "tokens", "savings_pct", "avg_accuracy"])
        
        for r in results:
            pct = r["top_pct"]
            avg_acc = sum(a["accuracy"] for a in accuracy_results if a["top_pct"] == pct) / max(1, len([a for a in accuracy_results if a["top_pct"] == pct]))
            writer.writerow([pct, r["files"], r["tokens"], f"{r['savings_pct']:.1f}", f"{avg_acc:.1f}"])
    
    print(f"CSV saved to {csv_path}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
