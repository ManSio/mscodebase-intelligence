# E56 — docs-only FTS channel + gold-language finding

Clean production index (7,314 chunks), code channel = quality.

## Exact-path metrics

| Arm | hit@1 | hit@5 | code h1/h5 | docs h1/h5 |
|---|---:|---:|---:|---:|
| code_only | 0.688 | 0.771 | 0.825 / 0.900 | 0.000 / 0.125 |
| docs_only | 0.021 | 0.062 | 0.000 / 0.000 | 0.125 / 0.375 |
| oracle | 0.708 | 0.812 | 0.825 / 0.900 | 0.125 / 0.375 |
| code4_docs1 | 0.688 | 0.750 | 0.825 / 0.875 | 0.000 / 0.125 |
| docs1_code4 | 0.021 | 0.750 | 0.000 / 0.875 | 0.125 / 0.125 |

p50 = 131 ms.

## Translation-normalized gold (same basename)

`docs/ru/X.md` counts as `docs/en/X.md`.

| Arm | hit@1 | hit@5 |
|---|---:|---:|
| code_only | 0.688 | 0.812 |
| docs_only | **0.750** | 0.750 |
| oracle | **0.812** | **0.917** |
| code4_docs1 | 0.688 | 0.875 |

## Verdict

- Docs retrieval is **not weak**: 6/8 docs queries return `docs/ru/X.md`, which
  is a correct translation of the `docs/en/X.md` gold. Exact-path scoring
  undercounts it as a miss.
- **Gold canonicalization is the bottleneck**, not ranking.
- A docs-only channel + explicit intent (agent says docs/code) reaches
  **0.812 hit@1 / 0.917 hit@5** with no LLM router and ~131 ms.
- H1 exact FAIL, translated PASS; H2/H3 exact FAIL, translated PASS; H4
  translated PASS; H5/H6/H9 PASS; H7 FAIL.

## Implemented

`Searcher.search_docs(query, limit)` + `search_code(intent="docs")` now use a
dedicated `docs/**` FTS channel. Verified on the 8 docs queries: exact@1 1/8,
same-basename@1 **6/8** (the 6 are correct `docs/ru/X.md` translations of
`docs/en/X.md`). Unit tests: `tests/test_search_docs.py` (2 passed).

## Translation dedupe + prune

- `search_docs()` now collapses `docs/{en,ru,zh,...}/X` to one key and prefers
  the query language (Cyrillic -> ru). This stops one document from taking 3/5
  slots. Live check: exact@1 1/8, same-basename@1 **6/8**.
- `SQLiteChunkStore.delete_files()` + full-run prune in
  `scripts/reindex_text_only.py` removes stale/excluded rows (no manual delete).
- Tests: `test_chunk_store_delete_files.py`, `test_search_docs.py` (3).
