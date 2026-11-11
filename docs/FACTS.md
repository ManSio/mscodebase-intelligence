# FACTS — the numbers this repository is allowed to quote

> One page, every public number, and the command that regenerates it.
> If a number is not on this page, it is not a fact yet.
> Update date: **2026-11-11**.

## 1. Identity

| Fact | Value | How to check |
|---|---|---|
| Version | `3.5.0` | `grep '^version' pyproject.toml` |
| Python | 3.14+ — the only version in the CI matrix | `pyproject.toml` / `.github/workflows/ci.yml` |
| License | MIT | `LICENSE` |
| Platform | Windows validated; Linux CI | `.github/workflows/ci.yml` |

## 2. Tool surface

| Fact | Value | How to check |
|---|---|---|
| Registered tools | **69** (36 core + 16 intel + 13 inline + 4 dev) | MCP startup log; `tool_help()`; `tests/test_tool_profile.py` |
| Visible by default | **17** (`MSCODEBASE_MCP_PROFILE=core`) | client tool list; `tool_help()` |
| Visible with `full` | **69** | `MSCODEBASE_MCP_PROFILE=full` + restart |
| `tool_help()` | lists profile, visible, hidden | one call |

`execute_script` is optional (`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`) and
counted separately from the 69.

## 3. Index of this repository (2026-11-08)

> Snapshot. The index is rebuilt whenever tracked files change, so these numbers
> move: regenerate them with the command below and update this table in the same
> commit that changes the documentation set.

| Fact | Value |
|---|---|
| Text chunks | **7 099** |
| Indexed files | **508** |
| Graph nodes | **13 098** |
| Graph edges | **49 136** |
| Full text reindex | **262 s**, 0 errors |

Command (regenerates all of it):

```bash
python scripts/reindex_text_only.py --project .
```

Chunk/file counts are also returned by `codebase(action="index", path="status")`.

## 4. Parsers and dependencies

<!-- stale-ignore -->
| Fact | Value | How to check |
|---|---|---|
| Grammars loaded | **31** | `python -c "from src.core.indexing.parser import CodeParser; print(len(CodeParser().parsers))"` |
| `tree-sitter` | **0.26.0** (latest Python binding on PyPI) | `pip show tree-sitter` |
| `tree-sitter-language-pack` | **1.25.0** (pinned) | `pip show tree-sitter-language-pack` |
| Outdated tree-sitter packages | 0 | `pip list --outdated` |
<!-- stale-ignore -->

A grammar bump changes chunking: treat it as a reindex + symbol-count change,
not a routine upgrade.

## 5. Search quality (measured 2026-10-25, 48-query panel)

These numbers are a **snapshot**; they are not re-measured on every commit.
Regenerate with the E30/E52/E57 harnesses under `experiments/`.

| Path | hit@1 | hit@5 |
|---|---:|---:|
| Code, quality mode | 0.825 | 0.900 |
| Overall, quality mode | 0.688 | 0.750 |
| Overall, auto docs route (E57) | 0.792 | 0.875 |
| Fast mode | 0.542 | 0.729 |
| Docs, exact path | 0.000 | 0.125 |
| Docs, same basename | 0.750 | 0.750 |

No 95% claim: static retrieval on this panel did not reach it.

## 6. Catalog-adapted features (2026-11-08)

| Fact | Value | How to check |
|---|---|---|
| AST-scoped grep noise removed | 14–32% of hits were in comments/strings (`capture_output` 94→81, `TODO` 25→17, `stale_detector` 145→103, 509 files) | `grep_code(..., scope="code")` vs `scope="all"` |
| Cost of `scope=code` | ≈1.2 s → ≈2.2 s on 509 files | same call |
| `investigate` latency | ~1–2 s per typical question (7 channels, 2 passes) | any `investigate` call |

## 7. External-corpus benchmark (E70–E73, 2026-11-11)

Two external repositories, questions and gold written by other people: query =
commit message, gold = files the commit changed, corpus pinned at a base commit
so the fix is not indexed. `hit@5` = the gold file is in the first five rows.

| Fact | Value | How to check |
|---|---|---|
| `psf/requests`, 25 commits, corpus `e331a288` | `tool` **12/25**, `search` 15/25, `grep` 19/25 | `python experiments/bench_2026_11/external.py --repo <bench>/requests --corpus <bench>/req-B --base e331a288 --limit 40` |
| `sqlalchemy`, 40 commits, corpus `8b62343` | `tool` **17/40**, `search` 18/40, `grep` 20/40 | same command with `--repo <bench>/sqlalchemy --corpus <bench>/sa-B --base 8b62343` |
| B1 dev (this repo), 71 commits | `tool` **19/71** | `python experiments/bench_2026_11/run.py --split dev` |
| Negative panel, 44 fabricated names | **0/44 answers** | `python experiments/false_abstain_2026_11/verify.py --corpus <bench>/sa-B --repo <bench>/sqlalchemy --base 8b62343 --panel experiments/scale_2026_11/tasks.jsonl` |
| `grep` beats the tool on commit localization | yes, both external repos above | the same two commands |

`<bench>` is the directory holding the cloned repositories and their
`git worktree` copies; the clone and worktree commands are in
`experiments/bench_2026_11/REPORT.md` ("Reproduce").

The tool is **not** better than grep at localizing a commit message on these
corpora; the claim "better than grep" was about symbol lookup on the generated
panel, and it does not generalize.

## 8. What is not a number

- "Better than RAG" is not claimed anywhere in this repository.
- The docs-vs-code gold mismatch (`docs/ru/X` for `docs/en/X`) is a labeling
  property, not a retrieval defect.
- Tool counts in older entries of `AGENTS.md`, `KNOWN_ISSUES.md` and blog posts
  are historical snapshots; this page wins.
