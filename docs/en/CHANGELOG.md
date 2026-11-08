# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - 2026-11-08

### Added
- **`investigate`** — one query, two-pass fan-out: `search` + `symbols` + `grep`
  in parallel, then `impact` + callers (`graph`) + `tests` + project `memory`
  for what pass 1 found. Results merge by `(file, line)` with the channels that
  found each item (`[search+graph]`); a slow or failing channel is reported in
  `degraded[]` instead of failing the call.
- **`grep_code`** — regex search with AST-aware `scope=code` that skips matches
  inside comments and strings, judged per match (not per line). Adapted from
  coderlm (MIT); path traversal, 1 MB file cap, binary skip, 512-char pattern.
- **Tool profile** — the server registers 69 tools and exposes 17 by default
  (`MSCODEBASE_MCP_PROFILE=core`); `full` exposes all, `MSCODEBASE_MCP_TOOLS`
  still overrides. `tool_help()` lists the hidden ones.
- **Ledger cache** — the startup contradiction check is reused for 6 hours while
  the diary (mtime/size/sha) and HEAD are unchanged.
- **Hot-reload for Phase 3** — `FreshnessChecker` reads the SQLite chunk store;
  files changed while the server was down are reindexed on the next search.

### Fixed
- `stale_detector` hung the whole event loop: `subprocess.run(capture_output=True)`
  for `git diff`/`git ls-files` deadlocks when stdout is the JSON-RPC pipe
  (AGENTS.md §5.16). Now `Popen + communicate`, with a bounded scan.
- Index status read only LanceDB while Phase 3 serves from SQLite, so
  `total_chunks` was 0 and every search/write tool was blocked.
- Health's git probe used `check_output` in a thread and timed out on every
  report; it now uses `rev-parse` with a 5 s budget and reports a metric.
- `AutoDocUpdater` rewrote `KNOWN_ISSUES.md` during reindex (third occurrence);
  registries are now opt-in (`MSCODEBASE_AUTODOC_LEDGERS=1`).
- Pre-commit gate ran `pytest -n auto`, which failed intermittently on
  git-spawning tests; it now runs serially (and skips gate-zero for docs-only
  commits: 229 s → 9.5 s measured).
- `search_code` accepted a 2000-character query and spent 47.5 s returning
  nothing; queries are capped at 512 characters.
- `scripts/reindex_text_only.py` failed with `ModuleNotFoundError: No module
  named 'src'` when invoked as documented.

### Changed
- Pinned `tree-sitter-language-pack==1.25.0` (was an open range; dev and
  runtime environments had drifted) and bumped `tree-sitter-php==0.25.1`,
  `tree-sitter-scala==0.26.9`, `tree-sitter-swift==0.7.4`.
  `tree-sitter==0.26.0` is already the latest Python binding on PyPI.

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
