---
title: "From a Test-Suite Trace to a Search Signal: the Bootstrap Pipeline Story"
description: "Part 4 of MSCodeBase Intelligence — Field Notes. Full source-material: why bootstrap started, Exp 7 (dynamic link), 7b (Tarantula), 8 (sysmon), 9 (static), 16 (portability), 17/E17 (search consumer). Honest about what is still experimental and can break."
tags: machinelearning, python, search, rag, codearchitecture, testing
---

<style>
/* Fix for coderlegion.com: tables with visible borders and background */
table {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
  background-color: #f9f9f9;
}
th, td {
  border: 1px solid #ddd;
  padding: 8px;
  text-align: left;
}
th {
  background-color: #4a90e2;
  color: white;
  font-weight: bold;
}
tr:nth-child(even) {
  background-color: #f2f2f2;
}
tr:hover {
  background-color: #e8f4f8;
}
</style>

> **Disclaimer & Status:** draft (source-material for the article). This is not a "feature advertisement", but an honest engineering story: figures are reproducible, weak points are named, and unaddressed risks are listed in the "What Could Go Wrong" section.

---

## Where It Started

The problem to which everything traces back: **RAG search across an unfamiliar codebase sees the code, but misses the intent.** Embeddings find a chunk by keywords, PropertyGraph finds a symbol by name, but to the question "where is the real business logic here, and what can I safely throw away?" no model answers — because the answer simply doesn't exist in static code representation.

Hence the **bootstrap pipeline** was born for indexing a new project across 4 steps:

1. **Entities** — types and data-classes as the core domain backbone;
2. **Entry points** — decorators (`@mcp_app.tool`) as the outer system boundary;
3. **Tests as ground truth** — tests as the only deterministic way to say *"this function is part of live execution logic"*;
4. **Git → ADR** — history of decisions extracted from commit logs.

Step 3 was the main battleground. The argument wasn't *"are tests needed"*, but **how to link a test to the exact function it actually executes**. Steps 1 and 2 relied on clean static analysis, whereas step 3 lacked an obvious static answer.

---

## First Clash: Static vs Dynamic (Exp 7)

Initial intuition: "A test has a name, a function has a name, let's link by name."
Measurement killed it instantly: **0 out of 109** tests in the evaluation sample named the function they actually executed. Import-only (file-level match) gave 77.9% — but file level is coarse noise (a single file contains dozens of functions).

We executed the entire suite (1,727 tests) using a custom `sys.settrace` plugin:

<pre>
[dynamic_trace] total tests traced: 1727
[dynamic_trace] tests executing >=1 src function: 1551 (89.8%)
[dynamic_trace] unique src functions executed: 1212
[dynamic_trace] avg src functions per linked test: 10.1 (median 6, range 1-118)
tests with exact-name target hit in dynamic set: 47 (2.7%)
A/B same session: 174.8s vs 198.6s -> overhead +13.6%
</pre>

**Takeaway: Dynamic tracing is the only deterministic linker, at the cost of a +13.6% one-time execution overhead.** And an uncomfortable truth surfaced immediately: a single test executes **10.1 functions** on average. "1 test = 1 function" was a naive myth. Thus, edges required a **ranker**: which of the 10 is the primary target?

---

## Ranking Failed (Exp 7b, Tarantula)

We tested the Tarantula heuristic ("a function called infrequently by many tests is the primary target"). 
*Hypothesis:* ≥60-70% of tests have an unambiguous candidate at rank≤3.  
*Reality:*

- rank≤3 applied to only **22.6%** of tests (7.5% rank=1) — **HYPOTHESIS REFUTED**;
- However, **precision was high**: manually inspected candidates at rank=1..3 were all accurate targets;
- The main offender: **shared utilities** like `safe_mkdir` / `get_data_root` (autouse fixtures, 234 callers each) and `project_hash` (223 callers).

**Verdict:** Tarantula is unsuitable for *selecting* the main target, but works well as a *confidence annotation* for ~16% of tests. `TESTS` edges are thus built from the complete trace without truncation — they are correct by construction and do not require lossy ranking.

Cross-verification with DEV.to publications (*A. Dawson "TRUE Coverage"* and *"Empirical Failure Modes in Autonomous Agents"*) confirmed both sides: static approaches fail across external codebases, shared utilities are a universal noise source, and **no one is building real-time TESTS edges for LLM search context** — validating our niche.

---

## Driver Switch Failed (Exp 8, sysmon)

Could `coverage run` (Python 3.14, `sys.monitoring`) run faster than our custom `sys.settrace` plugin?  
*Hypothesis:* Overhead <5%.  
*Measurement:*

<pre>
baseline: 184.88s | coverage: 221.78s -> overhead +19.96% (target <5% REFUTED)
</pre>

`coverage.py` was **~1.5x slower** than our lightweight plugin. `sys.monitoring` remains a validation oracle for spot-checks, while `sys.settrace` stays as the main execution driver.

---

## Static Companion — Not a Replacement (Exp 9)

We evaluated a full static score (AST L1 calls / L2 name tokens / L3 imports) against dynamic trace as ground truth.

| Signal | Hit | Recall | Precision | Mean Candidates |
|---|---|---|---|---|
| **L1 (direct calls from test body)** | 88.4% | 30.3% | 68.0% | 2.9 |
| **L2 (name tokens)** | 17.7% | 3.8% | 12.1% | — |
| **L3 (file imports)** | 91.6% | 72.0% | 21.8% | 41.4 |
| **Union (L1 + L2 + L3)** | 90.4% | 70.0% | 20.6% | — |

The initial assumption (*recall ≤ 30%*) was wrong: **union recall reached 70%**. Static signals were stronger than anticipated, but as a precise anchor L1 is narrow (precision 68%, 2.9 candidates), and as a wide net L3 is noisy (41.4 candidates). 

**Verdict:** Dynamic trace remains the edge driver; static analysis acts as a companion layer and candidate supplier for mock tests (which execute 0 real target functions dynamically).

---

## Portability Across External Codebases (Exp 16)

Does this generalize beyond our own repo? We tested the tracer across clean external Python repositories (e.g., `gemma_agent` at 97.3% linked tests) as well as smaller CLI tools, confirming that non-mocked external codebases yield even higher dynamic link ratios than mock-heavy internal codebases.

| Project | Language | Tests | Linked % | Overhead |
|---|---|---|---|---|
| **gemma_agent** | Python | 2882 (2874 pass) | **97.3%** (2805) | **+17.4%** (71.4s vs 60.8s) |
| **codebase-memory-mcp** | Go | 27 test funcs | — | `go test`: 51.0% pkg / **22.2% per-test** |

The limitation is honest: dynamic execution is currently **Python-only**; Go and TS require per-test tooling (e.g., `go test -coverprofile` across N executions). PropertyGraph itself is polyglot, but the edge builder remains Python-first.

---

## And Now: Edges Met the Consumer (E17)

Everything prior built `test ──TESTS──> function` edges inside PropertyGraph without leveraging them during search. E17 closed the loop:

- **Data:** 1,727 tests → **16,172 TESTS edges**, 1,595 Test nodes, 1,132 covered functions.
- **Implementation:** `SymbolIndexAdapter.get_tests_for_symbol()` (incoming `TESTS` edges) + `Searcher._append_tests_signal()`: appends up to 3 tests per function (capped at `min(len, 6)` per query), `graph_score = 0.4` vs 1.0 for definitions, sentinel `chunk_index = -(20_000_000 + line)` avoiding collisions with code chunks in RRF ranking.
- **Toggle:** `MSCODEBASE_TESTS_SIGNAL`, **on by default** — can be disabled via `MSCODEBASE_TESTS_SIGNAL=false`.

A/B evaluation on a live PropertyGraph (7 target functions, true answers from trace):

<pre>
hit@1: off=7/7, on=7/7 | hit@3: 7/7 | MRR(function): off=1.000, on=1.000
TESTS-signal: 6/7 queries received relevant covering tests in the response
graph_stage avg dt: off=3.43ms, on=3.27ms (within noise floor)
RETRACTION: 0 broken links (all files verified on disk)
</pre>

The core invariant holds — **function definitions are never displaced by test results** (`MRR = 1.0` in both arms): tests follow strictly as secondary context.

---

## What Could Go Wrong

A transparent list of risks and open validation items:

1. **A/B panel is narrow.** 7 identifier queries on a single repo without embedder/reranker layers. In a full pipeline, test signals might get lost in RRF.
2. **`graph_score = 0.4` is an empirical constant.** Chosen to stay strictly below function definitions, but unverified against BM25/reranker weight interactions.
3. **Pointer `:0`.** Test nodes from dynamic trace lack line numbers (`line=0`). Indexers must resolve test decorator line positions before enabling in prod.
4. **Hub-function noise.** `safe_mkdir` linked to 234 tests yields low-signal noise. The cap of 3 tests prevents payload flooding but doesn't solve irrelevance.
5. **Python-only.** Go/TS projects do not receive rich dynamic edges yet.
6. **Dependence on a green test suite.** On broken test suites, trace degrades (failing tests = missing edges). Bootstrap applies to stable branches only.
7. **Mock tests are blind.** 10.2% of tests execute 0 src functions; static companions cover 88 of 176, but not all.
8. **Graph reindex drift.** Rebuilding the PropertyGraph may alter node ordering slightly.
9. **CI scale limit.** Running trace on 100k+ test suites may breach CI execution windows.
10. **Clean-state status.** Verification was executed locally; clean CI state verification requires a PR merge.

---

## How to Reproduce

```bash
cd D:\Project\MSCodeBase

# 1. Dynamic trace (full run, +13.6% time)
$env:PYTHONPATH = 'D:\Project\MSCodeBase'
$env:TRACE_SRC_ROOT = 'D:\\Project\\MSCodeBase'
$env:TRACE_OUT = 'D:\\Project\\MSCodeBase\\experiments\\bootstrap\\trace_result.json'
python -m pytest tests/ -p src.core.bootstrap_trace_plugin -q --no-header -p no:cacheprovider

# 2. Edge linking (TESTS in live PropertyGraph)
python -c "from pathlib import Path; from src.core.bootstrap_tests import build_from_trace_file; \
print(build_from_trace_file(Path('experiments/bootstrap/trace_result.json'), Path('.')).to_dict())"

# 3. A/B consumer (control off / treatment on), reproducible
python -X utf8 experiments/bootstrap/e17_ab_tests_signal.py
#   expected: hit@1 7/7=7/7 · MRR 1.000/1.000 · 6/7 new tests · 0 broken links
```

---

## Experiment Matrix

| Exp | Date | Hypothesis | Verdict | Reference |
|---|---|---|---|---|
| **7** | 2026-09-15 | Dynamic > Static (0% vs 89.8%) | **CONFIRMED** (+13.6% overhead) | `EXPERIMENTS_LOG.md` |
| **7b** | 2026-09-15 | Tarantula rank ≤ 3 for ≥60% tests | **REFUTED** (22.6%, high precision) | `EXPERIMENTS_LOG.md` |
| **8** | 2026-09-16 | `sys.monitoring` overhead < 5% | **REFUTED** (+19.96%) | `EXPERIMENTS_LOG.md` |
| **9** | 2026-09-16 | Static recall ≤ 30% | **REFUTED** (union 70%, static companion) | `EXPERIMENTS_LOG.md` |
| **16** | 2026-09 | Portability on external repos | **CONFIRMED** (gemma 97.3%, commit 100%) | `EXPERIMENTS_LOG.md` |
| **17** | 2026-09-22 | `TESTS` edges drive search results | **CONFIRMED** (7/7 def-first, 6/7 with tests) | `EXPERIMENTS_LOG.md` |

---

## A note on how this was written

Every experiment, bug, failure, and idea here is mine — I earned them the hard way, in production, in public. AI worked as my editor: it helped me structure thoughts and polish my English. It did not invent the facts, because it has none of its own.

No AI detectors were consulted in the making of this disclosure. They have enough trouble agreeing on what I am.
