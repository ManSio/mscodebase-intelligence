# Search Pipeline — Current Contract

> **Current as of 2026-10-25.** The default runtime is Phase 3 text-first:
> SQLite FTS5/BM25 plus PropertyGraph. Dense, LanceDB and reranker stages are
> optional and are disabled unless configured. This document describes what the
> default path actually does; it does not describe the old pipeline as if it
> were still the default.

---

## 1. Contract

Input:

- a natural-language or identifier query;
- `mode`: `fast`, `quality`, `deep`, `context`, `ask`, `auto`;
- optional `layer`, `intent`, `limit`, `explain`.

Output:

- ranked chunks/files with metadata (`file`, `chunk_index`, `symbol_name`,
  `symbol_kind`, `layer`, line range, source);
- a stale-index banner when freshness checks fail;
- optional security metadata for untrusted indexed content.

The agent may pass `intent="docs"` or `intent="code"`. When `intent` is empty,
the tool compares the best docs-only BM25 score with the best code score and
routes to the docs channel when the margin exceeds `MSCODEBASE_DOCS_MARGIN`
(default `4.0`). There is no LLM in this decision.

## 2. Default Phase 3 path

```text
query
  │
  ├─ normalize / optional RU synonyms
  │
  ├─ SQLiteChunkStore.search(query, limit=20..50)
  │     └─ FTS5/BM25 over chunk text, symbol_name, docstring, file_path
  │
  ├─ if query looks like an identifier/path:
  │     └─ PropertyGraph stage adds exact symbol/file candidates
  │
  ├─ optional on-demand rerank (only if configured)
  │
  ├─ exact-name boost
  ├─ symbol deduplication
  │
  └─ return top-N
```

The SQLite path is deliberately shorter than the historical LanceDB pipeline.
In particular, it does **not** run RRF over BM25+dense+graph, MMR, co-change
boosts or P3 module-head anchors by default. Those stages live in the optional
dense/LanceDB path or in older code paths.

## 3. Candidate sources

### 3.1 SQLite FTS5/BM25

`SQLiteChunkStore.search` builds an FTS5 `MATCH` expression from query terms
(OR-joined, quoted), ranks with SQLite `bm25()`, and returns:

- chunk text and full text;
- file path, chunk index, symbol name/kind, docstring, layer;
- start/end line;
- `final_score` derived from the BM25 rank.

The table is content-linked (`content='chunks'`) with insert/update/delete
triggers, so deleting a file removes its FTS rows automatically.

### 3.2 Symbol and path signals

Identifier-shaped queries (`snake_case`, `CamelCase`, paths, `::`) get a
deterministic graph stage. The graph returns exact definition/reference rows
that FTS may rank below generic text matches. Duplicates are removed by
`file + chunk_index`.

### 3.3 Documentation channel

`Searcher.search_docs()` runs the same FTS5 store and keeps only `docs/**`
files. It collapses language variants (`docs/en/X`, `docs/ru/X`, `docs/zh/X`)
to one key, preferring the query language. This is a separate channel, not a
change to code ranking.

### 3.4 Optional dense/vector path

When `MSCODEBASE_DENSE_OFF=false` and a provider is available, vector search
runs over LanceDB or the configured backend. This path can add candidates but
is not required for the default contract.

## 4. Ranking and fusion

Default Phase 3:

1. BM25 order from SQLite.
2. Graph candidates appended for identifier queries.
3. Optional on-demand rerank of the top pool.
4. Exact-name boost for identifier queries.
5. Deduplicate by symbol.

Optional/historical path:

- reciprocal rank fusion of BM25, dense and FTS5 candidates;
- bucket weighting by intent and file type;
- co-change and exact-symbol boosts;
- non-code demotion (`tests/`, `docs/`, `experiments/`, `fixtures/`);
- MMR diversification;
- identifier anchors and P3 module-head anchors;
- multi-provider reranking.

These stages are configurable and are not applied on every query. Do not use
the old pipeline description to predict the default result order.

## 5. Documentation routing

Routing is a single cheap comparison:

```text
docs_max = best BM25 score among docs/**
code_max = best BM25 score among src/**, tools/**, scripts/**, tests/**
if docs_max - code_max > MSCODEBASE_DOCS_MARGIN:
    use search_docs()
else:
    use code search
```

Properties:

- one extra FTS query; no model call;
- explicit `intent` wins over the heuristic;
- threshold is configurable and was tuned on the 48-query panel;
- a code query with strong documentation vocabulary can still be misrouted;
  `intent="code"` is the escape hatch.

Measured on the panel: margin `4.0` gave 0 code false positives, docs top-1 in
5/8 docs questions, and 0.792 same-basename hit@1 overall. Treat that as a
panel result, not a universal constant.

## 6. Modes

| Mode | Path | Intended use |
|---|---|---|
| `fast` | FTS5 + optional dense if available; no reranker | Exact names, known paths, latency-sensitive calls |
| `quality` | Default hybrid path + optional rerank | Normal code/doc questions |
| `deep` | Quality plus graph context expansion | Cross-module investigation |
| `context` | Similar-code search from a fragment | Duplicate/similar implementation lookup |
| `ask` | Retrieval plus optional local LLM generation | Only when a local LLM profile is configured |
| `auto` | Chooses a mode from query shape | Default tool entry |

`fast` is materially less accurate on mixed natural-language questions than
`quality` on the internal panel (0.542 vs 0.688 hit@1). Use it intentionally.

## 7. Optional layers

| Layer | Flag / condition | Effect |
|---|---|---|
| Dense retrieval | `MSCODEBASE_DENSE_OFF=false` + provider | Adds vector candidates |
| On-demand rerank | `MSCODEBASE_ONDEMAND_RERANK=true` + provider | Re-scores top candidates |
| P3 module-head anchors | `MSCODEBASE_P3_ANCHOR=true` | Adds module-head chunks |
| RU synonyms | `MSCODEBASE_RU_SYNONYMS=true` | Expands Russian query variants |
| Non-code demotion | `MSCODEBASE_DEMOTE_NON_CODE=true` | Down-weights tests/docs/experiments |
| Intent-aware demotion | `MSCODEBASE_DEMOTE_INTENT_AWARE=true` | Keeps docs for docs intent |
| Docs auto-route | `MSCODEBASE_DOCS_MARGIN` | Docs/code channel choice |

## 8. Output contract

Each result carries enough metadata for the agent to explain itself:

- `file`, `chunk_index`, `start_line`, `end_line`;
- `symbol_name`, `symbol_kind`, `layer`;
- `final_score` and `source` (`sqlite_fts5`, `graph`, `docs_fts`, ...);
- optional `docstring`, callers/callees and security flags.

The tool response may include a stale-index warning. A warning is not a search
failure; it means the agent should refresh the index before trusting freshness.

## 9. Measured behavior

Internal panel: 48 real queries, clean index, `experiments/**` excluded, graph
present.

| Path | hit@1 | hit@5 |
|---|---:|---:|
| Code, quality | 0.825 | 0.900 |
| Docs, exact path | 0.000 | 0.125 |
| Docs, same basename | 0.750 | 0.750 |
| Overall quality | 0.688 | 0.750 |
| Overall auto docs route | 0.792 | 0.875 |
| Fast | 0.542 | 0.729 |

Limits:

- these are internal, not a universal benchmark;
- docs exact-path scoring undercounts correct translations;
- no static configuration or tested local reranker reached 95% hit@1;
- a two-channel repo map reached about 40/62/73% gold-file coverage at
  1k/2k/4k tokens with perfect routing, and PageRank alone was lower.

## 10. Debugging search

```text
debug_runtime_passport()
intel_get_runtime_status()
codebase(action="index", path="status")
search_code(query="...", explain=true)
```

Useful checks:

1. Is `chunks.db` non-empty? If not, run `scripts/reindex_text_only.py`.
2. Is `graph.db` empty? Run `scripts/rebuild_graph.py`.
3. Does the query look like docs? Try `intent="docs"` or `intent="code"`.
4. Compare exact-path vs same-basename before calling a docs result a miss.
5. For `fast` vs `quality`, run the same query in both modes and compare.

## 11. Non-goals

- An LLM router for every query. Routing is lexical and cheap.
- A static repo map that replaces iterative code search. It is context
  selection, not an oracle.
- Claiming 95% retrieval accuracy from a small internal panel.
- Hiding an empty graph or stale index behind a confident answer.
