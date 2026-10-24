# INVENTORY — re-score bundle `lab/e1-e2-2026-10-05/` @ `2918eb9` (+ `lab/overlap-fixture-fe4e465/` @ `450ddf2`)

SUPERSEDES nothing; EXTENDS `INVENTORY.md` (which inventoried the same bundle at the
older commit `3eecc40`, 20 files, no `runs/`). This file covers the **successor**
commit `2918eb9` (87 files under `lab/`).

Source: `tjonesit/crystals`, read-only. No git tree in any local repository was
modified. Scratch: `%LOCALAPPDATA%\mscodebase\audit-cache\trap-verify\`.

## 0. Commit verification (done before anything else)

| commit | full sha | date | message |
|---|---|---|---|
| `2918eb9` | `2918eb9ad47526abb19a2976def6ba691873bdd0` | 2026-10-06T22:12:44Z | `lab E1/E2: per-run rows (redacted), workspace fixtures, stand-ins, row-validity excerpt; both intervals re-derive` |
| `450ddf2` | `450ddf22d8ef1a2385b16c1dbd1386c73329030d` | 2026-10-06T19:59:03Z | `lab: overlap() reimplementation fixture at fe4e465 (416 rows, public inputs only)` |
| `3eecc40` | `3eecc40641b5c16c3b01848d8ff2517dcbda5b3c` | 2026-10-06T17:47:46Z | prior bundle (audited in `INVENTORY.md`) |

Both target commits exist (`gh api repos/tjonesit/crystals/commits/<sha>`).
The three are **linearly ordered**: `450ddf2` is the parent chain of `2918eb9`, so a
single checkout of `2918eb9` contains both directories.

```
2918eb9 -> 450ddf2 -> 3eecc40 -> 1b688a3 -> 99cd4df
```

## 1. Directory counts and sizes (recursive tree API, `truncated: false`, 155 blobs total)

```
 84 files   713551 B  lab/e1-e2-2026-10-05/
  1 file      1361 B  lab/e1-e2-2026-10-05/analysis-deps/
 51 files    22711 B  lab/e1-e2-2026-10-05/fixture/
  5 files     1893 B    fixture/app/
  1 file       107 B    fixture/assets/
  2 files       91 B    fixture/config/
  2 files      335 B    fixture/deploy/
  6 files     9282 B    fixture/docs/
  3 files       77 B    fixture/exports/
  2 files      167 B    fixture/jobs/
  1 file       119 B    fixture/queues/
 14 files     3110 B    fixture/reports/
  3 files       77 B    fixture/reports/runs/
  1 file        31 B      fixture/reports/runs/run-10/
  1 file        31 B      fixture/reports/runs/run-11/
  1 file        30 B      fixture/reports/runs/run-9/
  2 files      272 B    fixture/reports/transcripts/
  2 files      272 B      fixture/reports/transcripts/run-a/
  1 file       135 B        fixture/reports/transcripts/run-a/sub-run/
  7 files     1346 B    fixture/scripts/
  1 file        67 B    fixture/snapshots/
  2 files     1497 B    fixture/tests/
  4 files     83246 B  lab/e1-e2-2026-10-05/prereg/
  2 files     18680 B    prereg/analysis-code/
  3 files    452425 B  lab/e1-e2-2026-10-05/runs/
  1 file    109851 B    runs/e1/
  1 file    230893 B    runs/e2a/
  1 file    111681 B    runs/e2b/
  3 files     68073 B  lab/e1-e2-2026-10-05/scorers/
  8 files     70971 B  lab/e1-e2-2026-10-05/standins/
  1 file      2802 B    standins/venv-site/
  1 file      2802 B      standins/venv-site/boto3/
 12 files      5185 B  lab/e1-e2-2026-10-05/tasks/
  3 files     67857 B  lab/overlap-fixture-fe4e465/
 87 files    781408 B  lab/   (total)
```

Unchanged from `3eecc40` (byte-identical, verified by diff — see §4):
`README.md` 7933 B, `scorers/` 68073 B, `prereg/` 83246 B, `tasks/` 5185 B.

## 2. Row counts — his 111 / 223 / 114 CONFIRMED by actual count

Command (`Get-Content <file> | Measure-Object -Line`):

```
runs/e1/results.jsonl   lines = 111
runs/e2a/results.jsonl  lines = 223
runs/e2b/results.jsonl  lines = 114
```

**These are file line counts, all three correct as quoted.** Important
qualification: they are *banked* rows, which include void rows. After the
documented row-validity rule the analysable rows are fewer, and the design
resolves exactly:

| file | banked rows | void rows (reason) | analysable | design cell count | check |
|---|---|---|---|---|---|
| `runs/e1/results.jsonl`  | 111 | 3 (`helpful-refuse/peeked` 1, `none/peeked` 2) | **108** | 12 tasks x 3 arms x 3 reps = 108 | exact |
| `runs/e2a/results.jsonl` | 223 | 7 (`none/peeked` 3, `move-refuse/peeked` 2, `fact-refuse/peeked` 1, `sham-refuse/peeked` 1) | **216** | 12 x 6 arms x 3 reps = 216 | exact |
| `runs/e2b/results.jsonl` | 114 | 6 (`sham-refuse/peeked` 5, `helpful-refuse/peeked` 1) | **108** | 12 x 3 arms x 3 reps = 108 | exact |

The 3 extra E1 rows are voided **peeked attempts retained alongside their
replacement** — the affected cells each carry 4 rows
(`t26a/helpful-refuse`, `t19a/none`, `t3a/none`), which is why raw per-arm row
counts are 37/36/38 rather than 36/36/36. So "111 banked rows" is true and is not
an inflated denominator.

## 3. `RUNS-AND-FIXTURES.md` — what it says, and what is checkable

Full text is 24 lines. Its substantive claims:

- `runs/e1|e2a|e2b/results.jsonl` = "the banked result rows the analysis reads,
  one JSON object per run" (lines 5-6). **CONFIRMED** — one JSON object per line.
- `fixture/` = simulated workspace, `standins/` = stand-in tools (line 7).
  **CONFIRMED** — both present, 51 + 8 files.
- `analysis-deps/lablib.py` = "a verbatim excerpt of our harness, only the
  row-validity rule … Nothing else from the harness is included" (lines 8-9).
  **CONFIRMED** — the file is 35 lines and contains only
  `HARNESS_GEN`, `E0V3_EPOCH_TS`, `row_generation`, `ROW_INVALID_REASONS`,
  `row_invalid_reason`. No other harness code is present.
- Re-derivation recipe (lines 18-22) and his own run output (line 23).
  **Both headline numbers independently re-derived — see `REDERIVE_2918eb9.md`.**

### 3a. The privacy pass, exactly as stated (lines 11-15) — evidence per claim

| his claim (file:line) | what he says changed | independently observed | verdict |
|---|---|---|---|
| `RUNS-AND-FIXTURES.md:12` | `record`: a host path -> `<lab>/runs/<cell>/<run_id>` | all 448 rows carry `record` starting `<lab>/runs/e1/`, `<lab>/runs/e2a/`, `<lab>/runs/e2b/`; 448/448 | CONFIRMED |
| `RUNS-AND-FIXTURES.md:13` | `session_id`: Claude Code session id -> stable 12-hex sha256 prefix, "rows stay joinable" | all 448 rows: 448 distinct `session_id`, every one exactly 12 lowercase hex, 1:1 with `run_id` (1:1 joinable) | CONFIRMED |
| `RUNS-AND-FIXTURES.md:14` | per-run sandbox paths `/private/tmp/ws-<hex>/<hex>` in peek/action text -> `<ws>` | `<ws>` appears 9x, only inside `peek_matches[].action`, at `runs/e2a/results.jsonl:110` (x2), `:211`, `runs/e2b/results.jsonl:20,28,29,75,79` | CONFIRMED |
| `RUNS-AND-FIXTURES.md:15` | `scratch/` and `__pycache__` not copied | neither directory present under `lab/e1-e2-2026-10-05/` | CONFIRMED |
| `RUNS-AND-FIXTURES.md:15` | "A scan for host paths, usernames, keys and emails returned zero hits" | **emails are NOT literally zero — 3 exist, all on the reserved `.invalid` TLD (RFC 2606): `fixture/queues/mail.json:4`, `:8`, `standins/svc.py:527`.** Host paths / usernames / keys: zero (my sweep agrees). | **PARTLY IMPRECISE** |

That last row is the only wording defect found in the whole bundle: "zero hits"
for emails is true only under a filter that excludes `.invalid`. Immaterial as a
leak (RFC 2606 `.invalid` cannot be a real address) but it is a stronger claim
than the artifact supports. Full sweep in `PRIVACY_2918eb9.md`.

## 4. "Nothing else edited" — confirmed by diff, and one honest limitation

`git diff --stat 3eecc40 2918eb9`:

```
 67 files changed, 5157 insertions(+)
```

**Zero deletions, and no pre-existing file modified** — `README.md`, `scorers/*`,
`prereg/*`, `tasks/*` do not appear in the diff at all, so they are byte-identical
across the two commits. The claim "nothing else edited" (line 11) is verified.

**Limitation, stated rather than glossed:** because all three `runs/*.jsonl` are
**brand-new files** in this commit, the pre-redaction rows were never published.
The replacements are therefore observable but the substitution is not
falsifiable from public data. What *is* verifiable is the post-state, and it is
clean (see `PRIVACY_2918eb9.md`).

## 5. Integrity: git blob ids re-derived locally

9/9 blob ids match the API-reported values (CRLF-normalised; `git clone` on
Windows checks out CRLF, the blobs are LF):

```
runs/e1/results.jsonl                  blob=cd19a94d0cd0  MATCH
runs/e2a/results.jsonl                 blob=b16467ca2d28  MATCH
runs/e2b/results.jsonl                 blob=88398ea2ee9d  MATCH
analysis-deps/lablib.py                blob=2d0b4561bbc8  MATCH
RUNS-AND-FIXTURES.md                   blob=80f5f8189d63  MATCH
lab/overlap-fixture-fe4e465/….json     blob=665594fa1276  MATCH
README.md                              blob=ef764ab38ba0  MATCH
prereg/analysis-code/analyse_e1.py     blob=9eb452376e6e  MATCH
prereg/analysis-code/analyse_e2.py     blob=0063f0dd1466  MATCH
```

## 6. Relationship to the prior session's finding

`REDERIVE.md` (commit `3eecc40`) concluded **"nothing verifiable from this bundle
alone"** and recorded the two headline intervals as *not re-derivable* because no
per-run rows shipped. That condition no longer holds. This run supersedes that
specific finding; the earlier file is left untouched. Per §19.11 the old verdict is
**SUPERSEDED by `REDERIVE_2918eb9.md`**, not edited in place.