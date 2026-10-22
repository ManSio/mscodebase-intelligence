# ACTS — frozen act list for the delivery check

**Frozen:** 2026-10-06, before any run. 18 acts. Every act is a literal `ctx` string, because
`matches_ctx()` tests the key against the act's *text*, and for a write act that text is
`match_scope(ctx, target)` = path + first 600 chars when the payload exceeds 2000 chars.

Population is declared up front: **18 acts**. If the instrument reports a different count, the run is
invalid — not "mostly fine".

## Group A — word-boundary cases (H1, C1)

Short keys and the seven words the author listed as boundary-matched. Each act is designed so that the
key appears **inside a longer word** and must therefore NOT match.

| id | act text (`ctx`) | why it must produce no candidate |
|---|---|---|
| A1 | `pytest -q tests/ -k empty` | key `pty` sits inside `empty` |
| A2 | `npm run copying` | generic word `copy` sits inside `copying` |
| A3 | `git commit -m "guardrails update"` | `guard` sits inside `guardrails` |
| A4 | `ruff check src/ --select ARG` | `usage` does not appear; short-key probe only |
| A5 | `python -m src.cli graph_query` | no key at all — **C2 negative control** |

## Group B — substring cases that MUST still match (H2, C1 positive)

| id | act text (`ctx`) | expected |
|---|---|---|
| B1 | `python -m src.cli graph_query --action isolation` | ≥1 candidate (a long key appears literally) |
| B2 | `git commit -m "fix(negative-controls): resolve GitBash outside PATH"` | ≥1 candidate |
| B3 | `pytest tests/ -k duplicate_runs` | ≥1 candidate |

## Group C — short generic words as whole words (H1 boundary, must match when standalone)

| id | act text (`ctx`) | expected |
|---|---|---|
| C1a | `npm run build --mode bench` | `bench` as a whole word → matches a crystal keyed on it, if one exists |
| C2a | `scripts/check_board_status.sh` | `board` as part of a longer *identifier* — word boundary is on word chars, so `_` counts as a boundary |

## Group D — ordering cases (H3, H4, H5, C3, C4)

Order is only defined among crystals that (a) matched this act and (b) share a rotation tier. The
expectation rule is in `ORDER_RULE.md`.

| id | act text (`ctx`) | what it tests |
|---|---|---|
| D1 | `python -m src.cli graph_query --action isolation` | two candidates, same tier, clear overlap gap → order must differ between `rotation` and `overlap` |
| D2 | `python -m src.cli stale_detector` | two candidates, **different** tiers → order must be identical between modes |
| D3 | `bash scripts/check_third_party_data.py --all` | single candidate → order trivially stable, negative control for D1 |

## Group E — write-scope cases (H7)

| id | target | `ctx` | expected |
|---|---|---|---|
| E1 | `docs/research/note.md` | short body (<2000 chars) containing the key | key anywhere in the body counts |
| E2 | `docs/research/note.md` | body >2000 chars with the key **only after** char 600 | key must NOT count (subject scope) |
| E3 | `docs/research/note.md` | body >2000 chars with the key inside the first 600 chars | key MUST count |

## Group F — telemetry cases (H12)

| id | act | expected |
|---|---|---|
| F1 | `git commit -m "chore: telemetry"` with `CRYSTAL_ELIGIBILITY_LOG=1`, `CRYSTAL_STORE_ROOT=<temp>` | exactly one eligibility row per eligible candidate |
| F2 | the same act with `--dry` | **zero** eligibility rows and zero ledger writes |

## Reproducibility

Every act above is a literal string. No act is generated, sampled or paraphrased at run time. The
runner must print the sha256 of this file in its manifest, and the manifest must record
`CRYSTAL_ORDER`, `CRYSTAL_ELIGIBILITY_LOG`, `CRYSTAL_STORE_ROOT`, `CRYSTAL_DELIVERY_LOG`,
`CLAUDE_SESSION_ID`, the tree sha and the ledger path — the same pre-flight checklist every time, so
"it was left on a default" cannot happen again.
