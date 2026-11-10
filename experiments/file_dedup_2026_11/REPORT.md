# E72 — file-level dedup: negative result

Date: 2026-11-10/11. Frozen spec: `frozen/PLAN.md` (written before any code
change). Switch: `MSCODEBASE_FILE_DEDUP=file`, **off by default**.

## What was asked

The tool answers with chunks; a "which file" question wants files. On 10
sqlalchemy tasks 72 rows covered 51 files (0.71 files per row, worst case 8 rows
= 1 file). Hypothesis: 29% of the answer slots repeat a file, so grep — which
ranks whole files — wins on external repos.

The repeat share on a larger sample (20 commits, below) is 22% of rows, not 29%;
the direction is the same, the number is not. Both samples are reported rather
than the rounder one.

## What was measured

Corpora: `sqlalchemy` at `8b62343` (668 files / 34 984 chunks, 40 commits) and
B1 dev (71 commits, calibrated in E65/E67/E71).

```
sqlalchemy, 40 tasks          hit@1  hit@5
  tool, flag off                 8     11
  tool, flag on                  8     11     <- P1 (>=14) FAILED
  neighbours                    11     19
  search                        12     18
  grep                           7     20
```

```
B1 dev, 71 tasks              tool   neighbours  search  grep
  flag off                    19/71      38        22      2
  flag on                     19/71      38        22      2
```

**The flag changed no hit@5 number on either corpus**, and it did work: with the
flag on, the same answers carry **0 duplicate rows instead of 25**. So the
repeats were real and were removed — the score simply did not move.

`duplicate_positions.py`, 20 sqlalchemy commits, flag off:

```
rows=112  duplicate_rows=25 (0.22 of rows)
duplicate row positions (1-based in the answer):
  rank 2: 1   rank 3: 2   rank 4: 4   rank 5: 3
  rank 6: 5   rank 7: 3   rank 8: 7
duplicates at ranks 1-5: 10 of 25
```

So 10 of the 25 repeats sat inside the top-5 that hit@5 counts, and replacing
them with distinct files still produced 11/40 — the swaps were neutral: the
duplicate was not what kept the gold file out. What limits the tool is **which
distinct files rank where**, not that one file took several slots.

One more fact from the same run, unrelated to the flag but larger than it:
**6 of 20** sqlalchemy commits get an empty answer (0 rows) both with and
without the flag. On that repo the abstain is a bigger gap than dedup, and it is
not addressed here.

## The harm the flag does (P3)

20 probes built from the symbol index: functions with >= 2 distinct call lines
inside one file, asked as `where is <name> used`.

```
probes kept (file still contributes >= 2 rows, before and after):  5 / 20
```

Examples:

```
select_from                      lib/sqlalchemy/dialects/mssql/base.py   before=3 after=1
_join_fixture_compound_expression_1  test/orm/test_rel_fn.py              before=8 after=1
_get_custom_operator_dispatch    lib/sqlalchemy/sql/compiler.py          before=7 after=1
extend_string (kept)             lib/sqlalchemy/dialects/mysql/base.py   before=8 after=3
```

When the answer has >= 8 distinct files, the first pass fills all 8 slots and
the same-file rows are pushed out entirely — which is exactly the wrong answer
for a "where is X used" question. Two probes (`le_`, `to_instance`) never
contained the file before either; they are not losses, they are probes whose
answer was already wrong.

## Gates

| # | Gate | Result |
|---|---|---|
| P1 | sqlalchemy tool hit@5 >= 14/40 | **FAIL** (11, identical to flag off) |
| P2 | B1 dev >= 19/71 | PASS (19, identical) |
| P3 | >= 3 of 4 probe groups keep same-file rows | **FAIL** (5/20 = 25%; the frozen "3 of 4 groups" is 75%, i.e. 15 of 20 probes) |
| P4 | flag off byte-identical on 10 tasks | PASS (`sha256` equal, sequential rerun) |

P4 needed a second run: the first pair was measured while the sqlalchemy
benchmark held the same SQLite index, one baseline answer carried
`degraded: impact:InterfaceError`, and the two files differed. The difference
was the harness, not the code — with both runs sequential the two files are
`sha256`-identical.

## Verdict

The gap to grep is **not** a chunk-vs-file artifact. Dedup removes every
duplicate row (25 -> 0 on the same 20 commits) and hit@5 stays at 11/40, so the
repeated files were not what pushed the gold out of the top-5. The cost is real
though: "where is X used" loses its same-file rows (5 of 20 probes kept), because
once 8 distinct files are found the second pass never runs.

Consequence for the product: keep the switch experimental and off. Do not claim,
and do not ship, "dedup by file" as the explanation for the grep gap. The next
honest question is the one this run points at: why 6 of 20 external commits get
an empty answer at all, and why the distinct files rank below grep's.

## Reproduce

```
python experiments/file_dedup_2026_11/p4_identity.py --src <tree> ...
$env:MSCODEBASE_FILE_DEDUP="file"; python experiments/bench_2026_11/external.py ...
python experiments/file_dedup_2026_11/usage_probe.py --corpus D:\Project\bench-ext\sa-B
python experiments/file_dedup_2026_11/duplicate_positions.py --corpus ... --repo ...
```
