# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - 2026-09-27

### Added
- **F5 4-arm judged run** (4A unit-of-return): 16 frozen queries (8 code + 8 prose), 10 trials/arm, reader `opencode-go/longcat-2.0`, judge `opencode-go/qwen3.7-plus` (blind, disjoint from reader).
- Overall correct: A top-k chunks 16.3% (26/160), B top-1 full-doc 34.4% (55/160), C oracle 97.5% (156/160), D closed-book 0%.
- Code split: B 50.0% (40/80) vs A 6.3% (5/80), non-overlapping CIs; unit of return affects the reader, not gold-file hit.
- Prose split: A 26.3% (21/80) vs B 18.8% (15/80), overlapping CIs — fragile, no claim.
- Majority (strict >50% per query-arm): B 5/16 (F5S-13/B 5/10 tie counted out); guard: 0 `invalid` in trials=10 run (1 in t5 pilot, F5S-03/B).
- NodeRAG refuted on the same bench: TF-IDF baseline 80% vs graph BFS 70% — graph adds cost without gain here.
- Caveats: n=16 pilot scale; index snapshot not hard-frozen; raw answers path-normalized before commit, verdicts unchanged.

## [3.5.0] - 2026-09-22

### Added
- **TESTS-signal in graph-stage** (E17): Covering tests are now appended to symbol search results as a separate, lower-ranked group. This provides LLM context about which functions are covered by tests.
  - `SymbolIndexAdapter.get_tests_for_symbol()`: Resolves incoming `TESTS` edges for a function
  - `Searcher._append_tests_signal()`: Appends up to 3 tests per function with `graph_score = 0.4`
  - Sentinel `chunk_index = -(20_000_000 + line)` to avoid RRF collisions
  - Enabled by default via `MSCODEBASE_TESTS_SIGNAL` (can be disabled with `MSCODEBASE_TESTS_SIGNAL=false`)
  - 7 unit tests in `tests/test_graph_stage_e4.py`
  - Reproducible harnesses: `e17_ab_tests_signal.py`, `e17_wide_panel.py`, `e17_redteam.py`
  - **Findings:** hit@1 unchanged (94.3% both arms), TESTS-signal enriches 97.1% of queries with test context, overhead +15.3%, Red Team 5/5 attacks repelled
  - **Language coverage:** Python 34.0%, Other/TypeScript 0% (dynamic trace is Python-only)

### Changed
- Article draft `docs/blog/bootstrap-pipeline.md` updated with 35-query panel results and Red Team validation

### Fixed
- Applied article review feedback: removed incomplete `commit-` project from Exp 16 table, updated E17 section with full evaluation metrics, updated risks and Experiment Matrix

## [3.4.0] - 2026-09-21

### Added
- Bootstrap Pipeline external review documentation
- KNOWN_ISSUES deduplication (16 duplicates removed, 379→240 lines)

### Changed
- Experiments E11/E14: Embedder A/B benchmarks (gemma vs e5)
- Experiment harnesses committed

## [3.3.0] - 2026-09-20

### Added
- Two-pass symbol resolver (PR #20)
- Head-freshness gated symbol anchors
- Fail-closed ambiguous symbol writes

### Fixed
- CI lint/portability fixes
- Graph resolver: include bare-callee nodes in qualified-symbol lookup
- Reindex: honest ETA from log speed + progress in Finalizing

## [3.2.0] - 2026-09-15

### Added
- Scope resolution for data flow queries (`graph_query(action="flow", name=...)`)
- `condition_path` property on edges for control-flow context

### Changed
- Consolidated search tools: `search_code` is the ONLY search tool (smart_search, deep_search, context_search deprecated)

## [3.1.0] - 2026-09-10

### Added
- Verify-on-Read (VOR) with lazy validation
- Memory contamination retraction (ADR-0002)
- Shadow canary attack detection

### Fixed
- Memory contamination issues (48/48 confirmed, independent audit)
- Verify-on-read replication (facts v4, N=50)

## [3.0.0] - 2026-09-05

### Added
- PropertyGraph v3.0: Persistent knowledge graph with TESTS/DEFINES/CALLS edges
- Multi-project search support
- Resource monitor with adaptive throttling

### Changed
- **BREAKING:** Indexer is now per-project (not singleton) to support multi-window
- Symbol index migrated to PropertyGraph

## [2.x] - Earlier versions

See git history for detailed changelog.
