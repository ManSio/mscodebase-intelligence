# Search pipeline

> Rewritten 2026-11-08. The default runtime is **Phase 3 text-first**:
> SQLite FTS5/BM25 over parsed chunks plus a Tree-sitter/PropertyGraph.
> Dense, LanceDB and reranker stages exist but are optional and are marked.
> Numbers: [FACTS.md](../FACTS.md).

## 1. What a query goes through

```text
query
  │
  ├─ 1. Request guard        empty? >512 chars? → refuse with the reason
  │
  ├─ 2. Freshness (throttled) changed/new files → reindex in the background
  │
  ├─ 3. Candidate retrieval
  │       identifier-shaped?  → graph stage (exact location, ~ms)
  │       otherwise           → SQLite FTS5/BM25 over chunks.db
  │
  ├─ 4. Enrichment            symbol/path signals, layer filter, dedup
  │
  ├─ 5. Rerank (optional)     live embeddings over the top pool
  │
  ├─ 6. Docs routing          docs FTS score − code score > margin → docs
  │
  └─ 7. Format                file:line, symbol, score, warnings
```

## 2. The Phase 3 path (default)

`Searcher._sqlite_hybrid_search_async`:

1. **Candidates** — `SQLiteChunkStore.search(query, raw_limit)` where
   `raw_limit = min(max(limit × 4, 20), 50)`. The store answers with FTS5
   BM25 over chunk text (FILE/SYMBOLS/DOC are prepended to the text when
   `MSCODEBASE_AUGMENT_CHUNKS=true`).
2. **Filter** — optional `layer` (core/mcp/utils/tests/...) applied to the
   candidate set.
3. **Rerank (optional)** — with `MSCODEBASE_ONDEMAND_RERANK=true` (off by default; `investigate(rerank=true)` opts in per call),
   the top `MSCODEBASE_ONDEMAND_RERANK_TOP_N` candidates are re-scored with
   live embeddings; text is trimmed to `..._MAX_CHARS` before embedding.
   Without a provider the stage is skipped, not failed.
4. **Shape** — results carry `file_path`, `line`, `symbol_name`, `text`,
   `score`, `source` (`sqlite_fts5`).

This path never touches LanceDB, so it works with no vector table at all.

## 3. Identifier short-circuit

Queries that look like an identifier (`_IDENTIFIER_QUERY_RE`) skip retrieval
and go to the graph stage, which resolves the definition and its immediate
neighbours. Measured in the code comments: ~6.8 ms versus a vector search of
seconds. Non-identifier questions produce no graph hits and fall through to
the normal path.

## 4. Docs routing (E57)

`Searcher.prefers_docs(query)` runs one extra FTS query over `docs/**` and
compares the best docs score with the best code score:

```
docs_max − code_max > MSCODEBASE_DOCS_MARGIN (default 4.0)  → docs channel
```

- No LLM in this step; it is one query and a subtraction.
- Explicit `intent="docs"` or `intent="code"` overrides the automatic choice.
- `search_docs` deduplicates translations (ru/en/zh) and prefers the language
  of the query, so `docs/ru/X.md` and `docs/en/X.md` count as one document.
- Measured effect on the frozen panel: same-basename hit@1 0.688 → 0.792 with
  zero code false positives at margin 4.0.

## 5. `investigate` — one question, many channels

`investigate(query, limit=8)` is the default entry point and the reason the
model no longer has to choose a tool.

**Pass 1 (parallel, 12 s each):**

| Channel | What it runs | Weight |
|---|---|---:|
| `search` | SQLite FTS5/BM25 hybrid, docs routing | 0.6 |
| `symbols` | `symbol_index.search_symbols` per identifier | 1.0 |
| `grep` | regex over the two most code-like identifiers, AST-scoped, 15 s | 0.3 |

**Pass 2 (parallel, only if pass 1 produced files/identifiers):**

| Channel | What it asks | Weight |
|---|---|---:|
| `impact` | blast radius of the top identifiers | 1.2 |
| `graph` | direct callers of the top identifiers | 1.0 |
| `tests` | which tests cover the top files (skipped for test files) | 0.1 |
| `memory` | ADR/incident nodes sharing a token with the question | 0.4 |

**Merge:** key `(file, line)`; channels are unioned (`[search+graph]`), the
rank is `score + weight`, and rows are sorted by number of channels first, then
rank. Output is capped (8 rows, 180 chars per row).

**Failure:** a channel that raises or exceeds its budget is listed in
`degraded[]` (`grep:timeout`, `impact:AttributeError`); the rest of the answer
is still returned. A query with no hits returns "nothing found" — never a
plausible guess.

### 5.1 Evidence gate — a deterministic verdict

Every merged row is checked against facts, not plausibility. No model is called.

| Signal | Fact | Weight |
|---|---|---:|
| `definition` | the line declares the identifier (Python confirmed by `ast`) | 0.60 |
| `exact` | the identifier occurs verbatim on the row's line (a channel match alone is not enough; a line-less row keeps the channel claim) | 0.25 |
| `fresh` | live `mtime_ns` + `size` match the stat recorded at index time; grep rows scan the live tree, so they are fresh by construction | 0.10 |
| `ast` | the parser confirmed the declaration line (Python; the file is parsed only when a definition is possible there) | 0.05 |
| `graph` | the call graph has an edge for the identifier | 0.05 |
| `test` | a predicted test covers a top file | 0.05 |
| `memory` | an ADR / incident mentions the subject | 0.05 |

A references question ("who calls X") uses a different table: `exact` 0.45 and
`graph` 0.25, because a call site or a call-graph edge is the answer there and
the definition is context.

The verdict is printed as `verdict: answer (0.70) — class at file:line`:

- `answer` — the best row carries a verified declaration (definition question) or
  an occurrence / call edge (references question) and clears the floor;
- `caveat` — rows exist but none names the subject; they are neighbours;
- `ask_rewrite` — a Cyrillic question that names a proper-noun-like Latin word
  (`Corpus`, `Hub`) but no code token: ask for an identifier instead of
  inventing one. `MSCODEBASE_ASK_REWRITE=on` broadens this to every Cyrillic
  question without a code token; the measured trade is in
  `experiments/xerj_2026_11/evidence_gate/REPORT_REWRITE.md`;
- `abstain` — no row carries evidence (also when the subject does not occur and
  the graph does not know it).

Row markers are facts, not decoration: `✓def:class`, `✓def:function@368` (the
declaration is at line 368, the row points at the chunk start), `✓exact@211`
(the term is at line 211 inside the chunk), `⚠stale` (the file changed after
indexing), `⚠missing` (the index remembers a path the disk does not have),
`⚠outside project` (never read). On a definition question a verified declaration
is promoted above name matches; the promotion is stable and never drops a row.

Control/treatment on the frozen XERJ and `mcp_audit` panels, with kill criteria
frozen before the run: `experiments/xerj_2026_11/evidence_gate/REPORT.md`.
`MSCODEBASE_EVIDENCE_GATE=0` restores the previous behaviour.

## 6. Budgets and guards

| Layer | Budget | On timeout |
|---|---|---|
| `search_code` | 15 s (1 retry) | structured timeout error |
| `investigate` | 30 s outer, 12 s/channel, 15 s grep | `degraded[]`, partial answer |
| `grep_code` | 45 s | structured timeout error |
| `get_symbol_info` / `impact_analysis` | 15–20 s | structured error |
| Query length | 512 chars | refused with the length |
| Files scanned (grep) | 4 000; 1 MB per file | skipped and counted |
| Pattern length (grep) | 512 chars | refused |

## 7. What the pipeline does not do

- **No embeddings required.** The default path answers with FTS5 and the graph.
- **No LLM router.** Docs routing is a score comparison, not a model call.
- **No RRF/MMR over BM25+dense+graph in the default path.** Those exist in the
  legacy dense path only; mixing them into every query was not measured better.
- **No 95% claim.** See [FACTS.md](../FACTS.md) for the measured snapshot and the
  harness that produces it.

## 8. How to diagnose a bad result

1. `tool_help()` → are you on `core` and is the tool you expected visible?
2. `codebase(action="index", path="status")` → chunks > 0, files > 0?
3. Repeat the same query with `search_code(..., mode="quality")` and with
   `grep_code(..., scope="all")` → did retrieval miss, or did ranking reorder?
4. `investigate(...)` → which channels found the file (`[search]`, `[grep]`)?
5. Check the log tail: `%LOCALAPPDATA%/mscodebase/logs/mcp_global.log`.
