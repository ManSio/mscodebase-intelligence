---
title: "I Measured PageRank Token Savings on a Real Codebase. Here Are the Honest Numbers."
published: true
description: "I ran rigorous E2E experiments on PageRank-based context reduction: 5 graph densities, 50 queries with Gold Standard files, RAG comparison. PageRank gives +14pp over random on dense graphs, but RAG wins on file-level precision. Here's what actually works."
tags: machinelearning, python, ai, devtools
cover_image: 
---

> **TL;DR:** I ran 5 graph densities, 50 test queries with Gold Standard target files, and RAG comparison on a 50K LOC Python project. PageRank Top 20% gives **+14pp over random** on dense graphs (32% vs 18% Hit@Gold), but **RAG (BM25) beats both at 46%**. The previous "keyword accuracy" metric was misleading — real utility requires hitting the *specific* file that answers the question.

---

## The Setup

**Project:** MSCodeBase Intelligence (50K LOC Python, 129 files)

**Methodology:**

- **Gold Standard:** 50 queries → manually curated target file for each
- **3 Selection Methods:** PageRank (various densities), Random baseline, RAG (BM25)
- **Metric:** Hit@Gold — did the selection include the *exact file* that answers the query?
- **Token budget:** ~70K tokens (Top 20% of files) for fair comparison

**Tools:** NetworkX, tiktoken (cl100k_base), Python AST

---

## The Results

### Sparse Graph (imports only, 110 edges)

| Method | Hit@Gold | SUFFICIENT | Avg Tokens |
|--------|----------|------------|------------|
| RAG (BM25) | **46%** | 23/50 | 60,194 |
| PageRank | 18% | 9/50 | 65,821 |
| Random | 12% | 6/50 | 65,514 |

### Dense Graph (imports + class refs + function calls, 389 edges)

| Method | Hit@Gold | SUFFICIENT | Avg Tokens |
|--------|----------|------------|------------|
| RAG (BM25) | **46%** | 23/50 | 60,116 |
| PageRank | **32%** | 16/50 | 69,694 |
| Random | 12% | 6/50 | 65,476 |

### Key Numbers

- **RAG is 46% Hit@Gold** — nearly half the queries hit the exact right file
- **PageRank dense: 32%** — +14pp over random, +14pp over sparse
- **Random: 12%** — strong baseline because common keywords appear everywhere
- **Token savings are similar** across methods (~60-70K tokens), but RAG does it slightly cheaper

---

## Why My Previous Analysis Was Wrong

### The "Keyword Accuracy" Trap

My earlier posts measured "keyword accuracy" — does the selected context contain the query keyword *anywhere*? This gave misleadingly high numbers:

| Metric | PageRank (sparse) | PageRank (dense) |
|--------|-------------------|------------------|
| Keyword accuracy | 80% | 78% |
| **Hit@Gold (E2E)** | **18%** | **32%** |

**Why the gap?** Keywords like `search`, `error`, `lock`, `sql` appear in dozens of files. A random 25-file selection already covers 76% of queries by keyword. But to *actually answer* the question, you need the **specific implementation file**, not just any file mentioning the keyword.

### The Smart Summary Failure

I also previously tested a "Smart Summary" approach (feeding the LLM a compressed 2K-token overview of the repo). It seemed to give 90% accuracy on 10 easy queries, but on 50 real queries, it plummeted to 26%.

### The Random Baseline Is Strong

With 129 files, selecting 25 at random gives 12% Hit@Gold. Why? Because queries like "where is logging configured" — the keyword `logger` appears in 15+ files. Random selection often hits one of them. But it's the *wrong* file — it mentions logging but doesn't configure it.

---

## What Graph Density Actually Does

| Graph | Edges | Spearman ρ (rank vs size) | PageRank Hit@Gold |
|-------|-------|---------------------------|-------------------|
| Random | 0 | 0.02 | 12% |
| Import-only | 110 | 0.02 | 18% |
| +Class refs | 270 | 0.37 | — |
| +Func calls | 389 | 0.39 | **32%** |

**Denser graphs help PageRank** — Spearman correlation with file size rises from 0.02 to 0.39, and Hit@Gold goes from 18% to 32%. On sparse graphs, PageRank just selects the biggest files (which aren't necessarily the most important). Density breaks that coupling. But even dense PageRank **doesn't beat RAG** (32% vs 46%).

---

## Why RAG Wins

RAG (BM25) scores files by query keyword overlap — it's **query-aware**. PageRank is **query-agnostic** — it ranks files by global importance once, then you take the top N regardless of the user's specific question.

For a query like "where is DebounceBatch defined":

- RAG looks at the query terms, finds `rate_limiter.py` (high overlap on "DebounceBatch" + "defined"), and pulls it.
- PageRank looks at its pre-computed global graph, ranks `engine.py` and `runtime_coordinator.py` high (because they are central structural hubs), and completely misses `rate_limiter.py`.

You cannot use a static map of global importance to answer specific, localized questions. RAG is a GPS routing to a specific address; PageRank is just a map of the highway system.

---

## The Honest Takeaway: Correcting the Record

| Previous Claim | Reality | Why |
|----------------|---------|-----|
| "Top 20% = -2% savings" | +72% savings | Sparse graph artifact |
| "Smart Summary = 90% accuracy" | 26% accuracy | 10 easy queries ≠ 50 real queries |
| "PageRank doesn't work" | 32% Hit@Gold | Works, but modest (+14pp over random) |
| "centrality ≠ relevance" | ρ=0.39 (moderate) | Graph density helps decouple rank from file size |
| "PageRank beats RAG" | **False** | RAG 46%, PageRank 32% |

**PageRank works as a ranking signal** — it's 14pp better than random. But **it's not a retrieval system**. RAG's query-awareness makes it 14pp better than PageRank.

---

## What This Means

### For AI Code Tools

- Use PageRank as a **prior** — boost RAG scores with PageRank, don't replace RAG
- **Dense graphs matter** — import-only graphs are too sparse (18% → 32%)
- **Token savings ≠ utility** — saving 70% tokens but missing the target file is worse than full context

### For Developers

- Don't trust "X% accuracy" without knowing the metric — keyword accuracy ≠ Hit@Gold
- Always include a **random baseline** — it's embarrassingly strong
- Test with **Gold Standard files** — not just keyword presence

---

## The Math

```plaintext
Total: 129 files, ~406K tokens
Top 20% budget: ~25 files, ~70K tokens

Hit@Gold (E2E metric):
  RAG (BM25):      46% (23/50)
  PageRank (dense): 32% (16/50)  ← +14pp over random
  PageRank (sparse): 18% (9/50)
  Random:          12% (6/50)

Token savings: ~83% (all methods similar)
```

---

## Related Work

- **Aider** uses symbol-level elision — needs dense graph + query-aware retrieval
- **CodeGraph** does on-demand retrieval — correct approach
- **Codebase-Memory** honest metrics: 83% quality vs 92% for file-exploration

---

## Discussion

Has anyone measured Hit@Gold on their codebase? I'd love to see if the PageRank vs RAG gap (32% vs 46%) holds on larger projects (100K+ LOC).

What query-aware retrieval methods work best for your use case?

---

*Reproduce this yourself: scripts in [experiments/](https://github.com/ManSio/mscodebase-intelligence/tree/main/experiments). Run on your project and share results.*

---

*Part of my research on [MSCodeBase Intelligence](https://github.com/ManSio/mscodebase-intelligence) — an MCP server for codebase intelligence.*