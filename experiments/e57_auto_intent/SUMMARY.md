# E57 — automatic docs routing without LLM

## Lexical keyword router (E53-style)

| Arm | exact h1/h5 | same-basename h1/h5 |
|---|---:|---:|
| code_only | 0.688 / 0.771 | 0.688 / 0.812 |
| auto keywords | 0.625 / 0.708 | 0.708 / 0.812 |
| oracle | 0.708 / 0.792 | 0.812 / 0.917 |

False-positive docs intent: **4** code queries. p50 = 43 ms.

## BM25 margin router (implemented)

`docs_max - code_max > 4.0` -> docs channel, else code.

| Threshold | same-basename h1 | docs hit | code false positives |
|---|---:|---:|---:|
| 2 | 0.729 | 5/8 | 4 |
| 3 | 0.771 | 5/8 | 2 |
| **4** | **0.792** | **5/8** | **0** |
| 5 | 0.792 | 5/8 | 0 |
| 10 | 0.771 | 4/8 | 0 |

Exact-path overall at t=4: 0.708 (code exact unchanged; +1 docs exact).
Held-out (odd/even): best odd t=3 → even 0.875; t=4 full 0.792.

## Verdict

- Keyword router: +2 p.p. same-basename, but 4 code false positives.
- **BM25 margin router: +10.4 p.p. same-basename (0.688 -> 0.792), 0 code
  false positives, no LLM.** This is now `Searcher.prefers_docs()` and is used
  automatically by `search_code` when `intent` is empty.
- H1/H3/H4/H6/H8 PASS with margin; H2 PASS; H7 FAIL.
- Exact-path evaluation still undercounts `docs/ru/X` for `docs/en/X`.

## Implemented

`src/config/settings.py` (`MSCODEBASE_DOCS_MARGIN`, default 4.0),
`Searcher.prefers_docs()`, auto branch in `SearchCodeTool`.
Tests: `tests/test_search_docs.py` (4).
