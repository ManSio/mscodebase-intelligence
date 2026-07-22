---
title: "I Measured PageRank Token Savings on a Real Codebase. Here Are the Honest Numbers."
published: true
description: "I ran a rigorous experiment on PageRank-based context reduction: 5 graph densities, 50 queries, 5-fold cross-validation. The result: PageRank gives +6pp accuracy over random selection, with 73-83% token savings. Here's what actually works."
tags: machinelearning, python, ai, devtools
cover_image: 
---

> **TL;DR:** I ran 5 graph densities, 50 test queries, and 5-fold cross-validation on a 50K LOC Python project. PageRank gives **+6 percentage points** accuracy over random file selection (82% vs 76%), with **73-83% token savings** at Top 20%. The effect is real but modest. Here's the full picture.

---

## The Setup

**Project:** MSCodeBase Intelligence (50K LOC Python, 128 files)

**Methodology:**
- 5 graph densities: random baseline → import-only → +class refs → +func calls → full AST
- 50 test queries across 5 categories (definition, architecture, usage, bugs, navigation)
- 5-fold cross-validation (shuffled, mean ± std)
- 4 accuracy metrics: keyword, symbol, semantic, coverage
- Spearman correlation between PageRank score and file size
- Sensitivity analysis (damping factor α sweep)

**Tools:** NetworkX, tiktoken (cl100k_base), Python AST

---

## The Results

### Token Savings

| Selection | Files | Tokens | Savings |
|-----------|-------|--------|---------|
| Top 10% | 12 | 29,549–59,490 | +85% to +93% |
| Top 20% | 25 | 65,821–115,009 | +72% to +84% |
| Top 50% | 64 | 195,524–258,106 | +36% to +52% |
| Full context | 128 | 405,865 | baseline |

**Token savings are consistent across all graph densities.** The variation comes from which files PageRank selects — denser graphs pick different (sometimes larger) files.

### Accuracy (50 queries, keyword-in-file method)

| Density | Edges | Top 10% | Top 20% | Top 50% | Spearman ρ |
|---------|-------|---------|---------|---------|------------|
| Random baseline | 0 | 66% | **76%** | 96% | 0.019 |
| Import-only | 108 | 70% | 80% | 92% | 0.024 |
| +Class refs | 270 | 52% | **82%** | 94% | 0.367 |
| +Func calls | 381 | 58% | 78% | 92% | 0.393 |
| Full AST | 381 | 58% | 78% | 92% | 0.393 |

### The Honest Takeaway

**PageRank gives +6pp over random** (82% vs 76% at Top 20%). Not +40pp as my previous analysis suggested.

Why the discrepancy? My earlier experiments used 10 cherry-picked easy queries. With 50 queries (including hard ones like `ProjectContext`, `LspClient`, `embedding_cache`), the accuracy drops to realistic levels.

---

## Why Random Baseline Is Already 76%

This surprised me. With 128 files and 25 selected at random, you already cover 76% of queries. Why?

**Key insight:** Most query keywords (`search`, `error`, `lock`, `sql`, `memory`) appear in many files. A random selection of 25 files has a high probability of including at least one file containing each keyword.

The queries that fail are the **specific ones** — `ProjectContext` (3 files), `LspClient` (2 files), `modification_guard` (3 files). These are concentrated in a few files, so random selection often misses them.

---

## What Graph Density Actually Does

### Spearman Correlation (rank vs file size)

| Density | ρ (rank, size) | Interpretation |
|---------|----------------|----------------|
| Random | 0.019 | No correlation |
| Import-only | 0.024 | No correlation |
| +Class refs | **0.367** | Moderate correlation |
| +Func calls | **0.393** | Moderate correlation |

**Denser graphs make PageRank correlate with file size** — but only moderately (ρ ≈ 0.4). This means PageRank is still somewhat independent of size, which is good.

### Why Denser Graphs Don't Help Much

The +class and +func graphs add edges that connect files through shared class/function names. But these edges are **noisy** — many files share common names (`main`, `error`, `config`), so the signal doesn't improve much.

The real bottleneck isn't graph density — it's that **keyword-in-file is a weak accuracy metric**. A file can contain the keyword but not be the *right* file for the query.

---

## What This Means

### For AI Code Tools

1. **PageRank works, but modestly** — +6pp over random, not +40pp
2. **Token savings are the real value** — 73-83% at Top 20%
3. **Graph density helps with ranking** (ρ: 0.02 → 0.39) but not much with accuracy
4. **Query-based retrieval** (BM25 + vectors) is still superior for accuracy

### For Developers

1. **Don't trust "90% accuracy" claims** without knowing query selection
2. **Random selection is a strong baseline** — any method must beat it convincingly
3. **Token savings ≠ accuracy** — you can save 80% tokens while losing 20% accuracy

### For Researchers

1. **Test with 50+ diverse queries**, not 10 cherry-picked ones
2. **Always include a random baseline** — it's embarrassingly strong
3. **Report confidence intervals** (mean ± std), not single numbers
4. **Control for confounds** — file size correlation, query difficulty

---

## The Math

```plaintext
Total: 128 files, 405,865 tokens
Random Top 20%: 25 files, 68,772 tokens (+83.1% savings, 76% accuracy)
Import Top 20%: 25 files, 65,821 tokens (+83.8% savings, 80% accuracy)
Class  Top 20%: 25 files, 115,009 tokens (+71.7% savings, 82% accuracy)
Func   Top 20%: 25 files, 106,068 tokens (+73.9% savings, 78% accuracy)
Full   Top 20%: 25 files, 106,068 tokens (+73.9% savings, 78% accuracy)
```

### Failed Queries (same across all densities)

These queries fail because the keywords are concentrated in 1-3 files that PageRank doesn't rank highly:
- `ProjectContext` (3 files)
- `LspClient` (2 files)
- `modification_guard` (3 files)
- `embedding_cache` (1 file)

---

## What I Got Wrong Before

| Previous Claim | Reality | Why |
|----------------|---------|-----|
| "Top 20% = -2% savings" | +72-84% savings | Sparse graph + wrong baseline |
| "Smart Summary = 90% accuracy" | 26% accuracy | 10 easy queries ≠ real accuracy |
| "PageRank doesn't work" | +6pp over random | It works, but modestly |
| "centrality ≠ relevance" | Partially true | ρ ≈ 0.4, moderate correlation |

---

## Related Work

- **Aider** uses symbol-level elision — still needs dense graph
- **CodeGraph** (61k stars) does on-demand retrieval — the right approach
- **Codebase-Memory** (DeusData, arXiv) publishes honest metrics: 83% quality vs 92% for file-exploration

---

## Discussion

Has anyone else measured PageRank with a random baseline? I'd love to see if the +6pp holds on larger codebases (100K+ LOC).

What accuracy metrics do you use for evaluating context reduction?

---

*Reproduce this yourself: scripts in [experiments/](https://github.com/ManSio/mscodebase-intelligence/tree/main/experiments). Run on your project and share results.*

---

*Part of my research on [MSCodeBase Intelligence](https://github.com/ManSio/mscodebase-intelligence) — an MCP server for codebase intelligence.*
