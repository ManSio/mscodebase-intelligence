---
title: "From a Test-Suite Trace to a Search Signal: the Bootstrap Pipeline Story"
description: "Part 4 of MSCodeBase Intelligence — Field Notes. Full source-material: why bootstrap started, Exp 7 (dynamic link), 7b (Tarantula), 8 (sysmon), 9 (static), 16 (portability), 17/E17 (search consumer). Honest about what is still experimental and can break."
tags: machinelearning, python, search, rag, codearchitecture, testing
---



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

Does this generalize beyond our own repo? We ran the tracer against external projects:

| Project | Language | Tests | Linked % | Overhead |
|---|---|---|---|---|
| **gemma_agent** | Python | 2882 (2874 pass) | **97.3%** (2805) | **+17.4%** (71.4s vs 60.8s) |
| **commit-** | Python | 27 | **100%** | N/A |
| **codebase-memory-mcp** | Go | 27 test funcs | — | `go test`: 51.0% pkg / **22.2% per-test** |

Linked % on clean (non-mocked) third-party projects proved **higher** than on our own codebase (which relies heavily on mocks). The limitation is honest: dynamic execution is currently **Python-only**; Go and TS require per-test tooling (e.g., `go test -coverprofile` across N executions). PropertyGraph itself is polyglot, but the edge builder remains Python-first.

---

## And Now: Edges Met the Consumer (E17)

Everything prior built `test ──TESTS──> function` edges inside PropertyGraph without leveraging them during search. E17 closed the loop:

- **Data:** 1,727 tests → **15,931 TESTS edges**, 1,595 Test nodes, 1,108 covered functions (34.0% of all Python functions in the graph).
- **Implementation:** `SymbolIndexAdapter.get_tests_for_symbol()` (incoming `TESTS` edges) + `Searcher._append_tests_signal()`: appends up to 3 tests per function (capped at `min(len, 6)` per query), `graph_score = 0.4` vs 1.0 for definitions, sentinel `chunk_index = -(20_000_000 + line)` avoiding collisions with code chunks in RRF ranking.
- **Toggle:** `MSCODEBASE_TESTS_SIGNAL`, **off by default** — production behavior remains bit-for-bit untouched.

### Narrow A/B (7 target functions, identifier-only)

A/B evaluation on a live PropertyGraph (7 target functions, true answers from trace):

<pre>
hit@1: off=7/7, on=7/7 | hit@3: 7/7 | MRR(function): off=1.000, on=1.000
TESTS-signal: 6/7 queries received relevant covering tests in the response
graph_stage avg dt: off=3.43ms, on=3.27ms (within noise floor)
RETRACTION: 0 broken links (all files verified on disk)
</pre>

The core invariant holds — **function definitions are never displaced by test results** (`MRR = 1.0` in both arms): tests follow strictly as secondary context.

### Wide Panel (35 queries, functions with most TESTS edges)

To validate beyond the narrow 7-query panel, we ran a wide panel of 35 identifier queries (functions with the most TESTS edges):

<pre>
hit@1: off=33/35 (94.3%), on=33/35 (94.3%)
hit@3: off=34/35 (97.1%), on=34/35 (97.1%)
MRR(function): off=0.957, on=0.957
TESTS-signal: 34/35 queries received new covering tests (97.1%)
graph_stage avg dt: off=6.52ms, on=7.53ms (overhead +15.3%)
</pre>

**Critical finding:** TESTS-signal **does not improve hit@1** (off=on). It only **adds context** (tests) to already-found results: 97.1% of queries received new covering tests. This means TESTS-signal is **context for LLM**, not a search improvement. If LLM doesn't use tests, the signal is useless.

### Language Coverage (Critical Limitation)

TESTS-signal works **only for Python**:
- **Python:** 34.0% of functions covered by TESTS edges (1,108/3,256)
- **Other (Go, Rust, etc.):** 0% (716 functions without TESTS edges)
- **TypeScript:** 0% (11 functions without TESTS edges)

For non-Python projects, TESTS-signal **does not work at all**. Dynamic trace (pytest + sys.settrace) collects edges only for Python. For Go/TS, a separate connector is needed (go test -coverprofile, Jest coverage), but this **is not done**.

### Red Team: 5/5 Attacks Repelled

We tested TESTS-signal against 5 attack vectors:
- ✅ **Concurrency:** 10 threads × 100 calls = 1,000 calls in 17.2s, 0 errors
- ✅ **Boundaries:** function with 234 tests = 16.11ms (acceptable)
- ✅ **Abuse:** query for nonexistent function = 0 results (graceful degradation)
- ✅ **TOCTOU:** graph closed between calls = graceful degradation
- ✅ **Dependency failure:** PropertyGraph with nonexistent path = 0 results (graceful degradation)

**Conclusion:** TESTS-signal is resilient to concurrency, boundaries, abuse, TOCTOU, and dependency failures.

---

## What Could Go Wrong

A transparent list of risks and open validation items:

1. **Language coverage — critical limitation.** TESTS-signal works **only for Python**:
   - Python: **34.0%** of functions covered by TESTS edges
   - Other (Go, Rust, etc.): **0%** (716 functions without TESTS edges)
   - TypeScript: **0%** (11 functions without TESTS edges)
   
   This means for non-Python projects, TESTS-signal **does not work at all**. Dynamic trace (pytest + sys.settrace) collects edges only for Python. For Go/TS, a separate connector is needed (go test -coverprofile, Jest coverage), but this **is not done**.
   
   → **Risk:** hybrid repos (Python + TS) will receive TESTS-signal only for the Python part.
   → **Fix:** separate Go/TS connector (not in this experiment).

2. **A/B did not improve hit@1.** Wide panel (35 queries):
   - hit@1 off=33/35 on=33/35 (94.3%)
   - hit@3 off=34/35 on=34/35 (97.1%)
   - MRR(function) off=0.957 on=0.957
   
   TESTS-signal **does not help find the function** (hit@1 did not improve). It only **adds context** (tests) to already-found results: 34/35 queries received new covering tests (97.1%).
   
   → **Conclusion:** TESTS-signal is **context for LLM**, not a search improvement.
   → **Risk:** if LLM doesn't use tests, the signal is useless.
   → **Fix:** verify on real LLM pipeline (not in this experiment).

3. **Overhead +15.3% for wide panel.** Average graph_stage time:
   - off: 6.52ms
   - on: 7.53ms
   - overhead: +15.3%
   
   For bootstrap (one-time run) this is acceptable. For prod search — may be critical with many queries.
   
   → **Risk:** at 1000 queries/sec, overhead may be noticeable.
   → **Fix:** cache TESTS-signal (not done).

4. **Red team: 5/5 attacks repelled.** Tested:
   - ✅ **Concurrency:** 10 threads × 100 calls = 1,000 calls in 17.2s, 0 errors
   - ✅ **Boundaries:** function with 234 tests = 16.11ms (acceptable)
   - ✅ **Abuse:** query for nonexistent function = 0 results (graceful degradation)
   - ✅ **TOCTOU:** graph closed between calls = graceful degradation
   - ✅ **Dependency failure:** PropertyGraph with nonexistent path = 0 results (graceful degradation)
   
   → **Conclusion:** TESTS-signal is resilient to concurrency, boundaries, abuse, TOCTOU, and dependency failures.

5. **`graph_score = 0.4` is an empirical constant.** Chosen to stay strictly below function definitions, but unverified against BM25/reranker weight interactions.
   → Verify on full pipeline; constant may become a parameter.

6. **Pointer `:0`.** Test nodes from dynamic trace lack line numbers (`line=0`). Indexers must resolve test decorator line positions before enabling in prod.

7. **Hub-function noise.** `safe_mkdir` linked to 234 tests yields low-signal noise. The cap of 3 tests prevents payload flooding but doesn't solve irrelevance.

8. **Dependence on a green test suite.** On broken test suites, trace degrades (failing tests = missing edges). Bootstrap applies to stable branches only.

9. **Mock tests are blind.** 10.2% of tests execute 0 src functions; static companions cover 88 of 176, but not all.

10. **Graph reindex drift.** Rebuilding the PropertyGraph may alter node ordering slightly.

11. **CI scale limit.** Running trace on 100k+ test suites may breach CI execution windows.

12. **Clean-state status.** Verification was executed locally; clean CI state verification requires a PR merge.

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

# 3. Language coverage + wide panel (35 queries)
python -X utf8 experiments/bootstrap/e17_wide_panel.py
#   expected: hit@1 33/35 (94.3%) · TESTS-signal 34/35 (97.1%) · overhead +15.3%
#   critical: Python 34.0% covered, Other/TypeScript 0%

# 4. Red team (5 attacks)
python -X utf8 experiments/bootstrap/e17_redteam.py
#   expected: 5/5 attacks repelled (concurrency, boundaries, abuse, TOCTOU, dependency failure)

# 5. A/B consumer (control off / treatment on), reproducible
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
| **17** | 2026-09-22 | `TESTS` edges drive search results | **CONFIRMED** (7/7 def-first, 6/7 with tests; wide panel 35 queries: hit@1=94.3%, TESTS-signal=97.1%) | `EXPERIMENTS_LOG.md` |

---

## A note on how this was written

Every experiment, bug, failure, and idea here is mine — I earned them the hard way, in production, in public. AI worked as my editor: it helped me structure thoughts and polish my English. It did not invent the facts, because it has none of its own.

No AI detectors were consulted in the making of this disclosure. They have enough trouble agreeing on what I am.
