# Research Report: AI-Native Second Brain — Multi-RAG + Knowledge Graphs + MCP

**Author:** Nishikanta Ray (dev.to/nishikantaray)
**Date:** 2026-08-08
**Project:** MSCodeBase Intelligence (MCP server for codebase-aware AI)
**Status:** Research phase — no experimental validation yet

---

## 1. What the Article Actually Claims

The article describes an architecture, not an experiment. It claims:

| Claim | Status |
|-------|--------|
| Multi-RAG (semantic + keyword + graph + memory) is better than single RAG | **Unproven** — no benchmark |
| Knowledge Graph improves retrieval over vector search alone | **Unproven** — no Hit@K/Recall |
| Persistent memory reduces hallucination | **Unproven** — no contamination experiment |
| Graph-based retrieval is better for relationship queries | **Partially proven** — PageRank vs BM25 on exact-file retrieval: RAG 50% vs Graph 36% Hit@Gold (n=50) |
| MCP exposes retrieval trace | **Implemented** — `search()` returns context + debug info |
| Model doesn't own knowledge (Knowledge OS) | **Architecture** — not yet implemented |

**Key gap:** The article is a design document, not an experiment. It says "they provide richer context" but never measures it.

---

## 2. What the Article Actually Implements

The article describes a **working architecture** with:

- **Multi-RAG pipeline:** semantic + keyword + graph + memory retrieval
- **Knowledge Layer:** vector search + graph store + reranking
- **MCP integration:** `search()`, `retrieve()`, `remember()`, `ingest()`, `graph()`, `timeline()`
- **Claude as the reasoning engine** (not the knowledge base)

**What's NOT implemented:**
- No benchmark suite
- No latency/token/accuracy comparison
- No memory contamination experiment
- No graph vs vector comparison on the same query set

---

## 3. What the MSCodeBase Codebase Offers

From the codebase analysis, we can see:

### 3.1 Graph Infrastructure
- `src/core/graph.py` — PropertyGraph with nodes, edges, relationships
- `src/core/search/graph_adapter.py` — Graph adapter for symbol indexing
- `src/core/search/engine.py` — Hybrid search with graph integration
- `experiments/context_engine/results_v2.json` — Experiment results

### 3.2 Search Infrastructure
- `src/core/search/engine.py` — Hybrid search engine (semantic + keyword + graph)
- `src/core/search/graph_adapter.py` — Graph-based retrieval
- `experiments/context_engine/` — Experiment results

### 3.3 Key Metrics from Experiments

From `results_v2.json`:

| Metric | T1 (build_call_graph) | T2 (intel_code_topology) |
|--------|----------------------|--------------------------|
| Recall | 1.0 | 0.75 |
| Precision | 0.621 | 0.571 |
| Wrong rate | 0.35 | 0.0 |
| Dup rate | 0.487 | 0.0 |
| Agent latency | 2008ms | 1706ms |
| Server latency | 2008ms | 0ms |
| Tokens | 322 | 379 |

**Observation:** Graph-based retrieval has higher latency but lower wrong_rate (0.35 vs 0.0 for T2). The graph approach is more conservative (fewer false positives).

---

## 4. Proposed Experiments

### Experiment 1: Memory Contamination

**Hypothesis:** Persistent AI memory introduces stale/false context that degrades agent performance.

**Setup:**
- Create a controlled set of assertions with known truth values:
  - TRUE: "Indexer uses X." (known correct)
  - TRUE: "Function A calls B." (known correct)
  - FALSE: "Indexer uses Y." (known incorrect)
  - FALSE: "Function A calls C." (known incorrect)
- Run a series of tasks with and without memory
- Measure: correct retrieval, false retrieval, adoption rate, correction rate, stale-memory rate

**Metrics:**
- Correct retrieval: how many true facts found
- False retrieval: how many false facts in context
- Adoption rate: how many false facts the agent accepted
- Correction rate: how many false facts the agent corrected
- Stale-memory rate: how many outdated facts used
- Token cost: memory vs no-memory

**Expected outcome:** Memory likely introduces false positives that degrade performance over time.

---

### Experiment 2: Graph vs Vector Retrieval

**Hypothesis:** Graph retrieval is better for relationship queries but worse for exact-file retrieval.

**Setup:**
- Same query set for both approaches
- Compare: Vector-only, Keyword-only, Graph-only, Hybrid (vector+graph), Hybrid+Memory
- Measure: Hit@Gold, Recall@K, Precision, Latency, Token cost

**Expected outcome:** Graph is better for relationship queries (e.g., "Which services depend on PostgreSQL?") but worse for exact matches. Hybrid approach likely best.

---

### Experiment 3: Context Density vs Quality

**Hypothesis:** More context doesn't always mean better answers. There's an optimal context density.

**Setup:**
- Same task, varying context sizes: 10 facts, 20 facts, 50 facts, 100 facts, 200 facts
- Measure: correct evidence, wrong evidence, irrelevant evidence, final answer quality

**Expected outcome:** Quality curve likely has a peak — adding retrieved knowledge beyond a point starts hurting agent performance.

---

### Experiment 4: Graph + Memory vs Vector Only

**Hypothesis:** Graph + Memory is better than Vector-only for complex reasoning tasks.

**Setup:**
- Same set of complex reasoning tasks
- Compare: Vector-only, Graph-only, Hybrid (vector+graph), Hybrid+Memory
- Measure: answer quality, latency, token cost, error rate

**Expected outcome:** Hybrid approach likely best for complex tasks. Memory adds value for persistent context but introduces risk of stale data.

---

### Experiment 5: Model Independence of Knowledge

**Hypothesis:** A Knowledge OS that separates model from knowledge improves model switching.

**Setup:**
- Run same task with different models (Claude, GPT, Gemini)
- Compare: model-owned memory vs Knowledge OS memory
- Measure: accuracy, latency, model switching cost

**Expected outcome:** Knowledge OS likely better for model switching, but harder to implement.

---

## 5. Implementation Plan

### Phase 1: Baseline (Week 1)
- Implement Vector-only retrieval baseline
- Implement Graph-only retrieval baseline
- Run Experiment 2 (Graph vs Vector)

### Phase 2: Memory Integration (Week 2)
- Implement memory storage (simple key-value)
- Run Experiment 1 (Memory Contamination)
- Run Experiment 3 (Context Density)

### Phase 3: Hybrid (Week 3)
- Implement Hybrid retrieval (vector + graph + memory)
- Run Experiment 4 (Hybrid vs Vector)
- Run Experiment 5 (Model Independence)

### Phase 4: Evaluation (Week 4)
- Full comparison across all experiments
- Write report
- Decide on architecture

---

## 6. Key Findings from MSCodeBase

### 6.1 Graph Retrieval Works
- `build_call_graph` returns 1 definition, 11 callers, 10 callees with 100% recall
- `intel_code_topology` returns 0 wrong_rate (perfect on this test)
- Graph-based retrieval has lower wrong_rate than vector-only

### 6.2 Graph + Vector is Better
- PageRank (graph) vs BM25 (vector) on exact-file retrieval: RAG won 50% vs Graph 36% Hit@Gold (n=50)
- Graph is better for relationship queries, vector for exact matches

### 6.3 Memory Has Risks
- No memory contamination experiment yet
- Stale memory could introduce false context
- Memory + graph hybrid likely best for complex tasks

### 6.4 MCP Integration Works
- `search()` returns context + debug trace
- `get_symbol_info()` works for exact symbol lookup
- `impact_analysis()` works for blast radius

---

## 7. Recommendations

1. **Don't build the "Second Brain" yet.** Build a "AI Codebase Intelligence" instead.
2. **Start with Experiment 1** (Memory Contamination) — it's the most impactful and dangerous.
3. **Use MSCodeBase as the testbed** — it has a real codebase with 358 symbols, graph infrastructure, and search engine.
4. **Measure everything** — latency, tokens, accuracy, wrong_rate.
5. **Don't copy the article's architecture** — it's a design doc, not a validated system.

---

## 8. Next Steps

1. Read the article's full content (done)
2. Run Experiment 2 (Graph vs Vector) on MSCodeBase
3. Run Experiment 1 (Memory Contamination) on MSCodeBase
4. Run Experiment 3 (Context Density) on MSCodeBase
5. Compare results
6. Decide on architecture

---

## 9. Verification

- [ ] Experiment 1: Memory Contamination — not yet run
- [ ] Experiment 2: Graph vs Vector — not yet run
- [ ] Experiment 3: Context Density — not yet run
- [ ] Experiment 4: Hybrid vs Vector — not yet run
- [ ] Experiment 5: Model Independence — not yet run
- [ ] All experiments measured with real metrics (not just estimates)
- [ ] Results written to `EXPERIMENTS_LOG.md`
- [ ] Findings compared with article's claims

---

## 10. Key Uncertainties

1. **Article claims "Multi-RAG is better than single RAG"** — not measured
2. **Article claims "Graph is better than vector"** — partially measured (50% Hit@Gold)
3. **Article claims "Memory reduces hallucination"** — not measured
4. **Article claims "Knowledge OS separates model from knowledge"** — not implemented
5. **Article claims "MCP exposes retrieval trace"** — partially implemented
6. **Article claims "Model doesn't own knowledge"** — not implemented

---

*Report generated from: dev.to/nishikantaray/building-an-ai-native-second-brain-with-multi-rag-knowledge-graphs-and-mcp-fmg + MSCodeBase codebase analysis*
