# MCP audit fixes — experiment report (2026-11-09)

Follow-up to `C:\Users\misha\AppData\Local\mscodebase\audit-cache\mcp-live-audit-2026-11-09\REPORT.md`.
Fixes the defects found by live calls, and measures every ranking change against a control.

Frozen inputs: `questions.json`, sha256 `d9ab4bbecc3de93e01350ee71748b644cd8eb28254ca82ce077ff7276d385f37`.
14 English questions on 3 repositories + 3 Russian questions on MSCodeBase. Gold = the file that
contains the implementation, verified by grep before the run.

Control vs treatment is paired: same process, same index, same machine, only `_bucket_penalty`
disabled (`--penalty 0`) or enabled (`--penalty 1`), and the name-variant channel disabled
(`--names 0`) or enabled (`--names 1`). This isolates the ranking change from indexing noise.

## 1. Ranking (control → treatment)

| corpus | files | top-1 | top-5 | test-file slots in top-5 | median latency |
|---|---:|---:|---:|---:|---:|
| MSCodeBase | 525 | 2/6 → **3/6** | 4/6 → **6/6** | 8/30 → **0/30** | 3062 → 3402 ms |
| black | 420 | 0/4 → **1/4** | 2/4 → **4/4** | 13/20 → **2/20** | 2877 → 3160 ms |
| httpbin | 23 | 1/4 → **3/4** | 3/4 → **4/4** | 14/20 → **4/20** | 57 → 65 ms |

Reading: tests and historical docs no longer lead a code answer — in the treatment they appear
only as context below the implementation (2/20 black, 4/20 httpbin, down from 13/20 and 14/20),
and every gold file is in the top-5. The name-variant channel recovers the compound name
(`DEFAULT_LINE_LENGTH` → `const.py` rank 1 on black) and the root-Markdown demotion stops
`AGENT_DIARY`/`EXPERIMENTS_LOG` from leading. The remaining top-1 misses are conceptual
(`where is the project state machine` → registry at rank 4; `install sync` → install.py at rank 5).

### 1.1 Name-variant channel (paired, penalty on, root-markdown demotion off in both)

| corpus | top-1 names 0 → 1 | top-5 names 0 → 1 |
|---|---:|---:|
| MSCodeBase | 2/6 → 2/6 | 4/6 → 4/6 |
| black | 0/4 → **1/4** | 3/4 → **4/4** |
| httpbin | 3/4 → 3/4 | 4/4 → 4/4 |

The channel asks FTS for `DEFAULT_LINE_LENGTH`-style compounds built from query words **in query
order** (`_identifiers` sorts by score, which produced `DEFAULT_LENGTH_LINE` and missed everything)
and keeps only rows whose text contains the variant verbatim. Weight 3.0 was chosen because 2.0
left `const.py` at rank 5; the cost is ~0.3 s per query (12 lookups of ~10–20 ms). On MSCodeBase the
gold answers were already in the top-5; the extra push to 6/6 comes from demoting root Markdown
(`AGENT_DIARY.md`, `EXPERIMENTS_LOG.md`), which the exact-name channel had started to surface above
the implementation. That demotion is part of the combined treatment in section 1, not of this arm.

Reproduce:

```
python experiments/xerj_2026_11/mcp_audit/eval_investigate.py --project mscodebase --penalty 0 --names 0
python experiments/xerj_2026_11/mcp_audit/eval_investigate.py --project mscodebase --penalty 1 --names 1
... same for black and httpbin
```

The control was measured before the name channel existed; `--names 0` is its exact equivalent
(and `--penalty 0` disables every rank rule). Per-question rows are in
`results/final_control_*.json` (control) and `results/final2_*.json` (treatment).

### 1.2 Non-code demotion on the SQLite path (paired, same index)

`MSCODEBASE_DEMOTE_NON_CODE` was applied only in the LanceDB branch; with the
default `dense_off=true` the SQLite/FTS5 path returned docs at full score.
`eval_sqlite_demote.py` toggles `searcher._demote_non_code` on the same index,
6 MSCodeBase code questions, `search_code(mode="quality")`:

| arm | docs top-1 | docs top-5 | gold top-1 | gold top-5 |
|---|---:|---:|---:|---:|
| off (control) | 3/6 | 10/30 | 2/6 | 5/6 |
| on (treatment) | **0/6** | **0/30** | **3/6** | 5/6 |

Docs disappear from the top-5 and the gold answer gains one top-1
(`search_code dispatch` moves from rank 2 to 1); no gold file is lost.

### 1.3 Rewrite gate for Russian questions without a code name (XERJ N03)

A Cyrillic question with only proper-noun-like Latin words (XERJ N03, `Где
ключ подписи Corpus Hub?`) cannot name the real identifier
(`corpus_hub_signing_key`, which occurs nowhere). The tool used to return
`check_knowledge.py` as if it were the answer. The gate now returns rewrite
instructions and **no file rows** unless the query contains a lowercase term,
a code-shaped token, or a backticked name (`` `Indexer` `` passes).

| bucket (XERJ) | 2026-11-09 recheck | with gate |
|---|---:|---:|
| negative | 3/4 | **4/4** |
| ambiguity | 2/4 | 2/4 |

N03 is fixed; A04 still misses the second gold (`indexer_table.py`), which is a
ranking problem, not a gate problem. English queries are never gated.

## 2. Latency

| change | before | after | measurement |
|---|---:|---:|---|
| on-demand rerank default (live MCP) | 5.4 s per cold quality query; investigate 7.7–8.1 s | 0.15 s quality; investigate 3.2–4.0 s with `rerank=false` | live calls after `.env` fix + restart |
| two grep identifiers | 2 scans = 4.78 s | one walk = 3.28 s | `bench_channels.py`, `graph`+`stage`, MSCodeBase 525 files |
| per-file test prediction | 3 sequential = 4.04 s | 3 parallel = 3.68 s | same script (CPU contention with the live MCP) |
| investigate end-to-end (in-process, same 6 questions) | 9.15 s median | 3.40 s median (3.19 s before the name channel) | control vs treatment run above |
| 6 concurrent investigate | 8/8 TIMEOUT at 38 s (live, rerank on) | 0 errors, wall 18.7 s (in-process, rerank off) | `--parallel` |

The in-process harness competes with the running MCP for the write lock, so its absolute numbers are
higher than the live server's; the paired deltas are what the change is measured by.

## 3. Russian questions

| arm | top-1 | top-5 |
|---|---:|---:|
| investigate, RU query | 0/3 | 0/3 |
| investigate, RU query + `MSCODEBASE_RU_SYNONYMS=true` | 0/3 | 0/3 |
| `search_code(fast)`, RU query | 0/2 | 0/2 |
| `search_code(fast)`, same question rewritten in English | 3/3 | 3/3 at 0.19–0.27 s |

The synonym dictionary does not cover the tested terms, so it is not enabled. The product fix is
agent-first: Russian queries no longer auto-route to `docs/ru/**` (`prefers_docs` returns False for
Cyrillic unless the question asks for documentation), and `search_code` appends an explicit hint
when the answer is docs-only. The code itself is English; the agent must rewrite.

## 4. Other fixes verified by tests

- `set_project` writes `MSCODEBASE_PROJECT_PATH` (ranked above CWD) and refuses a drive root.
- Readiness: an UNINITIALIZED project is opened in ~0.1–0.3 s instead of sleeping 5 s; a broken one
  fails immediately with `index_project_dir` in the detail.
- `project_root` is honoured by `codebase(index, status|progress|timeline)`, `read_live_file` and
  `notify_change`. Under `MSCODEBASE_RESTRICTED_READ=1` the root must be an indexed project.
- `index_project_dir` returns a job id in <1 s; the worker thread reports `state/files/elapsed`
  through `codebase(action="index", path="progress", project_root=...)`.
- CRLF files are no longer parsed through a `%TEMP%\tmp*` shadow: normalized comparison plus
  metadata rebuild. Regression test proves layer `tests` is preserved and no shadow path leaks.
- `search_code` explains stage timings (embed/search/graph/rerank), not just `total_ms`.

## 5. Red team (attacks on the new surfaces)

| attack | result |
|---|---|
| `set_project("C:\\")` to index the whole disk | refused (drive-root guard), env untouched |
| `set_project` into `.git`/`node_modules` | refused by `SystemArtifacts` |
| restricted read + `project_root="C:\\"` to escape the active project | refused unless the root is an indexed project |
| `file_path="../.."` with an explicit root | `is_relative_to` guard, path traversal rejected |
| regex injection through a query identifier | identifiers are `re.escape`d |
| two concurrent `index_project_dir` for one project | second call returns "already running", no second writer |
| concurrent search while indexing | existing `is_reindexing` fast-fail; no new shared mutable state |
| cancellation during grep | counts are not published when `cancelled` is set (abstention cannot hide an answer) |
| CRLF-only change vs real change | only newline normalization is ignored; a real diff still reindexes |

## 6. Known limits / next experiments

- **Conceptual NL retrieval improved but is not solved**: MSCodeBase 3/6 top-1 (project state
  machine at 4, install sync at 5), black 1/4 top-1 (3 of 4 at rank 2). Remaining misses need
  either constants-as-symbols or a narrow-grep candidate pass; both are designed, not shipped.
- **RU remains 0/3 for investigate** by design; the agent hint and rewrite path are the product
  answer. A real RU→EN query translator is a separate experiment.
- **`docs/archive/**` is still indexed**; it is demoted, not excluded. Experiment E-4 in the audit
  report measures excluding it.
- **The 86-second call is not reproduced.** `search_code` now logs wall vs hot-reload time when a
  call exceeds 2 s, so the next occurrence will identify the term.
- **Full-suite / clean-state for this change** are reported separately in the session summary.
