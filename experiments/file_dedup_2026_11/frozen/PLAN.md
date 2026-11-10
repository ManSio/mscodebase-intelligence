# File-level dedup — frozen plan (written before the first run)

Date: 2026-11-10. Question this answers: *the tool answers with chunks; a
file-level question wants files. Is that why grep wins on external repos?*

The hypothesis was formed **after** the numbers (`psf/requests` 10 vs 19,
`sqlalchemy` 11 vs 20) and before any code change. The bar below is written
now and is not edited after a result is seen.

## What was measured to motivate it

10 sqlalchemy tasks, up to 8 rows each:

```
rows=72  distinct_files=51  ->  0.71 files per row
worst case: 8 rows = 1 file
```

29% of the answer slots repeat a file that is already shown.

## Change under test

One env switch, `MSCODEBASE_FILE_DEDUP`:

- empty / unknown -> shipped behaviour, byte-identical answer (P4);
- `file` -> after ranking, a **two-pass fill**: first one row per file (best
  rank wins), then the remaining rows fill the tail up to `limit`.

The "usage" question ("where is X used") is the reason for the second pass: on
such a question several rows of one file are the answer, so they must survive
when there are fewer distinct files than `limit`. Nothing is dropped that a
shorter answer could not already drop.

## Corpus (neither questions nor gold are ours)

| corpus | base | tasks | note |
|---|---|---|---|
| `sqlalchemy` | `8b62343` | 40 | 668 files / 34 984 chunks |
| B1 dev (this repo) | `7c2c7a3` | 71 | calibrated corpus, anchors from E65 |

Same rule as B1/B2: query = commit message, gold = files the commit changed,
corpus pinned at the base so the fix is not indexed.

## Bar (all four, frozen)

| # | Gate | Pass |
|---|---|---|
| P1 | sqlalchemy `tool` hit@5 | **>= 14 / 40** (from 11) |
| P2 | B1 dev `tool` hit@5 | **>= 19 / 71** (no loss against E71) |
| P3 | usage probes: answers that kept their same-file rows | **>= 3 of 4** probe groups |
| P4 | default off | answer text byte-identical on 10 tasks |

## P3 protocol (usage questions, because the flag can hurt them)

Probe built from the graph, not written by hand: take functions that the index
records with >= 2 distinct call lines **inside one file**, ask
`where is <name> used`, and count whether that file still contributes >= 2 rows.

Frozen: 20 probes drawn by hash order from the graph, first 20 with a
same-file multi-call site; a probe counts as kept if the file appears twice in
the answer both **before** and **after** the flag.

## Decision rule

- P1..P4 pass -> ship `file` as the default in a follow-up commit (its own PR,
  with the numbers above).
- P1 or P2 fails -> keep the flag experimental, write the negative result in
  `EXPERIMENTS_LOG.md`, do not touch the default.
- P3 fails -> dedup only when the question is a file-level intent; that is a
  new design, so stop and ask the owner.

## What would make this invalid

- Any tuning of `limit`, the bar, or the probe list after the first result.
- Running P3 probes on tasks that were used to form the hypothesis.
- Reporting the flag-on number without the flag-off number from the same code.
