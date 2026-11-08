# Hooks and gates

> Rewritten 2026-11-08 against `.githooks/pre-commit`,
> `.opencode/plugin/mscodebase_gate.ts`, `scripts/*` and `.github/workflows/ci.yml`.
> Each gate below was read in source; runtimes were measured when noted.

A commit passes through **three layers**. They overlap on purpose: the host-level
plugin catches the model, the git hook catches every commit regardless of host, CI
catches what a dirty working tree can hide.

```
agent/host ──► .opencode/plugin/mscodebase_gate.ts   (per git commit, in-session)
git commit ──► .githooks/pre-commit                   (12 gates + gate-zero pytest)
push / PR  ──► .github/workflows/ci.yml               (6 jobs)
```

## 1. OpenCode plugin (host-level hook)

File: `.opencode/plugin/mscodebase_gate.ts`. It runs only for `bash` tool calls whose
command matches `git commit`.

| Gate | Mode | What it does |
|---|---|---|
| `stale_detector` | **block** (`MSCODEBASE_STALE_GATE=off` to disable) | Compares version claims in docs with the code; drift > 0 aborts the commit |
| `graph_query isolation` | **advisory** (`block`/`off` possible) | Counts nodes that would be orphaned by the commit; text is appended to the tool result instead of blocking |

Details that matter for debugging:

- It calls `python -m src.cli <tool> '<json>'` in the project directory, i.e. the
  same tool classes as MCP but without the protocol.
- Interpreter: `MSCODEBASE_PY`, default `<repo>/venv/Scripts/python.exe`.
- Every call is logged as JSON lines to
  `MSCODEBASE_GATE_LOG` (default `%TEMP%/opencode/mscodebase_gate.log`).
- Any failure is swallowed and logged; only a deliberate block throws.
- The isolation gate costs ~8 s per `git commit` (measured in the log), the stale gate
  is fast. Both run before the git hook, so a slow first gate is felt by the agent.
- Since 2026-11-08 the plugin skips the isolation gate when every staged file is
  documentation (`*.md`, `*.txt`, `*.rst`): docs cannot orphan graph nodes, and this
  removes the wait on docs-only commits. The stale gate still runs — docs are exactly
  what it checks. Verified by driving the plugin with a temp repo: a staged `README.md`
  produced `isolation_skipped`, a staged `a.py` produced `isolation`.
- Known limitation: while the MCP process holds the database lock, the CLI waits up to
  8 s for it, then answers `base: cached` with an empty changed-files list. Treat the
  advisory as best-effort; the git hook and CI do not depend on it.

## 2. Git pre-commit hook (repository)

Active when `git config core.hooksPath` = `.githooks` (this repository). Installed or
checked by the `install_git_hooks` tool
(`action = install | uninstall | status`) or by setting `core.hooksPath` manually.

Budget per gate: `MSCB_PRECOMMIT_GATE_TIMEOUT` (default 900 s). Gate-zero (the full
`pytest tests/`) is skipped automatically when only documentation files are staged, and
can be skipped with `MSCB_PRECOMMIT_FAST=1`.

| # | Command | Blocks on |
|---|---|---|
| 0 | `pytest tests/` | any failing test (skipped for docs-only commits) |
| 1 | `scripts/verify_diary.py` | `✅` claims in `AGENT_DIARY.md` that the contradiction ledger cannot confirm |
| 2 | `scripts/stale_detector.py --staged` | version drift between staged docs and `pyproject.toml` |
| 3 | `scripts/check_tool_names.py` | dead `intel_*`/tool names in documentation |
| 4 | `scripts/negative_controls_runner.py` | a registered guard that cannot fail |
| 5 | `scripts/check_layer_boundaries.py` | `core` importing `mcp`/`sources` outside the transitional allowlist |
| 6 | `scripts/architecture_linter.py` | architecture invariants (registry, cycles, stale names) |
| 7 | `scripts/lock_guard.py` | active git lock files (advisory) |
| 8 | `scripts/check_known_issues.py` | `KNOWN_ISSUES.md` over 300 lines or missing monthly archive |
| 9 | `scripts/check_third_party_data.py` | personal data / verbatim third-party dumps in staged files |
| 10 | `scripts/check_parallel_sessions.py` | a staged file that another worktree is editing |
| 11 | `scripts/ruff_gate.py` | lint errors on staged Python |
| 12 | `scripts/gate_cli.py` (`tools/verification/gates.py`) | G1 population, G2 referent, G3 generalization, G4 control |

Two consequences worth remembering:

- A gate that turns red because of another session's untracked files is still a red
  gate. Fix the cause or commit with an explicit, documented `--no-verify`.
- The hook runs `pytest` on every non-doc commit; measure before blaming the agent for
  a 3-minute commit.

## 3. CI (`.github/workflows/ci.yml`)

| Job | What it proves |
|---|---|
| `test (ubuntu-latest, 3.14)` | full suite with coverage (`-n auto`) |
| `test (windows-latest, 3.14)` | the validated platform; catches Windows-only deadlocks |
| `clean-state` | fresh clone + venv + lock install + full suite; also runs negative controls |
| `manifest-parity` | our manifest extractors vs pinned `osv-scanner` on the polygon corpus |
| `docker-build` | the remote image still builds |
| `transport-equiv-e2e` | stdio and Streamable HTTP return the same answers |

CodeQL runs separately (`.github/workflows/codeql.yml`). Python 3.14 is the only
supported version.

## 4. What each layer is for

- **Plugin** — catches the agent before `git commit` returns, with a message the model
  can read.
- **Git hook** — catches humans and any host; the only layer that runs the full test
  suite by default.
- **CI** — catches what depends on a clean tree: lockfile drift, clean-state installs,
  Docker, transport equivalence.

Do not "fix" a red gate by disabling it. If a rule is wrong, change the rule and the
test that guards it in the same commit.
