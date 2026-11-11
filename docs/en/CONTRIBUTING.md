# Contributing — MSCodeBase Intelligence

[English](CONTRIBUTING.md) · [Русский](../ru/CONTRIBUTING.md) · [中文](../zh/CONTRIBUTING.md)

> Version 3.5.0 · Python >= 3.14 · MIT

A local MCP server: it indexes a repository with Tree-sitter, stores chunk text
in SQLite FTS5 plus a PropertyGraph, and answers code questions over MCP. Read
`AGENTS.md` (repository root) before your first change — it holds the operating
rules and the root-hygiene contract (§0.6: the allowed root set).

## 1. Layout

```
src/core/        indexing, search, graph, intelligence, guards (never imports mcp)
src/mcp/         server, tool classes, transports (depends on core, not the reverse)
src/providers/   embedder / reranker implementations (llama.cpp, LM Studio, ONNX)
src/config/      settings.py — every knob is an env var with a default
scripts/         operational + gate scripts (reindex, verify_clean_state, lint)
tools/           developer tooling (verification gates, knowledge checks, pipelines)
experiments/     probes and frozen inputs; excluded from indexing and from pytest
tests/           ~240 test modules at top level, plus tests/e2e and tests/fixtures
docs/            canonical documentation; docs/FACTS.md owns every quotable number
```

Layering is enforced: `scripts/check_layer_boundaries.py` fails on `core → mcp`
imports and on tool-layer dependencies that bypass the core.

## 2. Setup

```powershell
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence
python -m venv venv; venv\Scripts\activate; pip install -e ".[dev]"
```

`pip install -e .` is enough for the text-first runtime. Models are optional and
never download silently: `install.py` is text-first by default and only downloads
with `--with-models` (`models_enabled`); `--sync-only` copies code into the install
root without touching pip or models.

## 3. Tests and lint

`pyproject.toml` sets `addopts = "-v --tb=short -m 'not slow and not benchmark'"`.
That default matters:

```bash
python -m pytest tests/ -q                    # slow + benchmark excluded (addopts)
python -m pytest tests/ -m "not benchmark"     # includes slow tests
python -m pytest tests/ -q -n auto --cov=src   # what CI does (coverage gate: 38%)
```

A green `pytest tests/ -q` does **not** mean slow tests pass. CI runs the
`not slow and not benchmark` selection with `--cov=src --cov-fail-under=38` on
ubuntu-latest and windows-latest, Python 3.14 only. Lint: `ruff check src/ tests/`
(CI) or `python scripts/ruff_gate.py` (pre-commit).

## 4. Adding a tool

A tool is a class, a registration entry, and a profile decision.

```python
class MyTool(MCPTool):
    def __init__(self, services):
        super().__init__(services, tool_name="my_tool")

    async def execute(self, query: str) -> str | dict:
        indexer = self.resolve_indexer()   # per-project, not a global singleton
        ...
```

1. **Class** — subclass `MCPTool` in `src/mcp/tools/<area>.py`. Rules enforced by
   review and gates: dependencies via `self._services` (DI), no module-level
   globals; readiness from `RuntimeCoordinator` / `require_index()`, not your own
   check; return `str` or a JSON-serialisable `dict`; raise `ToolError` (or
   `IndexNotReadyError` / `RateLimitError`) for failures so the caller gets a
   `status` (`error`/`warning`/`timeout`) and a `recoverable` flag; decorate
   `execute` with `@error_boundary("<tool>", timeout_ms=...)`.
2. **Writes** — go through `WriteTool.execute` (`src/mcp/tools/write_tools.py`),
   decorated with `@modification_guard(pagerank_min=0.05, blast_min=10, ack_ttl=600)`.
   The guard denies writes on load-bearing files until `ack_impact` presents a
   valid impact token; do not add a second, undecorated write path.
3. **Registration** — append the class to `tool_classes` in
   `src/mcp/server_tools.py::register_all_tools()`. Do not register it directly on
   the MCP app elsewhere: the profile filter runs after all groups register.
4. **Profile** — put it in `CORE_PROFILE` (the 17-tool default surface, one entry
   per intent) or leave it visible only under `MSCODEBASE_MCP_PROFILE=full`. The
   counts are asserted in the module docstring: 36 core + 16 intel + 13 inline +
   4 dev = 69.
5. **Test and docs** — add a unit test under `tests/`; anything touching
   retrieval or the index needs a case that would fail if the tool silently
   returned empty. If the surface changed, update `tool_help`-visible text and any
   doc that lists tools.

## 5. Commits and pull requests

Conventional Commits, imperative, atomic:

```
feat(search): add code-aware BM25 term field

Restate the diff, not the intent. Explain why when the why is not obvious.
```

- Subject <= 72 chars, no trailing period, blank line before the body; breaking
  change as `type(scope)!:` plus a `BREAKING CHANGE:` footer.
- Stage files explicitly (`git add src/core/x.py tests/test_x.py`). `git add -A`,
  `git add .` and `git commit -a` are forbidden — a checkout can be shared with
  another agent or worktree, and a bulk add sweeps their unfinished work in. Run
  `git worktree list` and `git status` first; a file edited elsewhere is blocked
  by `scripts/check_parallel_sessions.py`.
- No generated artifacts or one-off files: `docs/generated/MODULE_INDEX.md` is not
  tracked, `experiments/**/results` is not indexed, and the root set is fixed by
  `AGENTS.md` §0.6. One concern per PR; self-review the diff before requesting
  review: every deleted line intentional, description no richer than the diff.

## 6. Gates

`core.hooksPath = .githooks`; `.githooks/pre-commit` runs these (900 s budget per
gate, `MSCB_PRECOMMIT_GATE_TIMEOUT`):

| Gate | Script |
|---|---|
| gate-zero + diary | `scripts/verify_diary.py` (full `pytest tests/`; skipped for docs-only commits or `--skip-gate-zero`) |
| version drift | `scripts/stale_detector.py --staged` |
| tool names | `scripts/check_tool_names.py` |
| negative controls | `scripts/negative_controls_runner.py` |
| layer boundaries | `scripts/check_layer_boundaries.py` |
| architecture invariants | `scripts/architecture_linter.py` |
| git locks (advisory) | `scripts/lock_guard.py` |
| known-issues size | `scripts/check_known_issues.py` |
| third-party data | `scripts/check_third_party_data.py` |
| parallel sessions | `scripts/check_parallel_sessions.py` |
| lint | `scripts/ruff_gate.py` |

CI adds `bump_version.py --check`, `disk_guard.py --check`, `pip-audit`,
`verify_clean_state.sh --no-clone`, `manifest_parity.py` and the
transport-equivalence e2e job. Check CI with `gh run list --branch <branch>` and
`gh run view <id> --log-failed`, not by assumption.

## 7. Documentation and registers

- Numbers (chunks, files, nodes, edges, quality, timings) live **only** in
  `docs/FACTS.md`, with the command that regenerates them.
- Canonical pages exist in three languages (`docs/en`, `docs/ru`, `docs/zh`); a
  change to one is a three-file change. Historical material in `docs/blog`,
  `docs/research`, `docs/archive` keeps its banner and date — do not rewrite it.
  Reference a fact as `(file, commit SHA, record ID)`, not `file:line`: lines rot.
- Registers: `AGENT_DIARY.md` (one diary; `DEV_DIARY.md` is a redirect),
  `KNOWN_ISSUES.md` (<= 300 lines, older entries move to
  `docs/archive/KNOWN_ISSUES_YYYY_MM.md`), `EXPERIMENTS_LOG.md`, `WISDOM.md`.
  Update them in the same commit; a second diary or a second `KNOWN_ISSUES.md` is
  a defect, not a variant.

**Verified against:** `pyproject.toml`, `.github/workflows/ci.yml`,
`.githooks/pre-commit`, `src/mcp/server_tools.py`, `src/mcp/tools/base.py`,
`src/core/modification_guard.py`, `src/core/error_handler.py`, `install.py`,
`AGENTS.md` (§0.6), directory listing of `src/`, `tests/`, `scripts/`, `tools/`,
`experiments/`.
