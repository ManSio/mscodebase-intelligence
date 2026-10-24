# OVERLAP FIXTURE — `lab/overlap-fixture-fe4e465/` @ `450ddf2`, package pin `fe4e465`

Deterministic only; no LLM call. Package tree cloned read-only to scratch
(`crystal-memory` @ `fe4e465`), nothing written into any repository.

## 0. Headline

| check | result |
|---|---|
| Row count claimed 416 | **416 CONFIRMED** (16 acts x 26 essences) |
| My independent reimplementation vs shipped values | **416 / 416 match** (denominator 416) |
| Package `overlap()` @ `fe4e465` vs shipped values | **416 / 416 match** |
| Shipped generator re-run verbatim -> byte-for-byte identical JSON | **CONFIRMED** |
| Essence inputs identical to what the fixture hashed | **26 / 26 sha256 identical** |
| Rows where I differ | **none** |
| Non-zero rows | 171 / 416 (so the match is not a table of zeros) |

## 1. Commit and tree pins verified

```
450ddf2  lab: overlap() reimplementation fixture at fe4e465 (416 rows, public inputs only)
         package_commit = fe4e465058cdf5c35cad542f9f0848e8f7c34c2d   MATCH
         catalogue_tree = 8da5e640d970c7ba0e47148b5255450e2982312b   MATCH
```

Independently confirmed against `Tirthahq/crystal-memory`:

```
git rev-parse HEAD            -> fe4e465058cdf5c35cad542f9f0848e8f7c34c2d
git rev-parse HEAD:catalogue  -> 8da5e640d970c7ba0e47148b5255450e2982312b
```

`crystal_act.py` in `tjonesit/crystals` @ `2918eb9` is **byte-identical to
`crystal-memory` @ `fe4e465`** after CRLF normalisation
(sha256 `8bf054eb4a76448cb6dba44578ab12e60809096d2619b5778d0ddc457b936342`;
the only difference is 1570 CRLF pairs introduced by the Windows checkout). So
the `crystals` bundle does ship the exact package code the fixture was computed
with.

## 2. What the rows actually carry — the key structural fact

Each of the 416 rows has exactly three keys:

```json
{"act_id": 0, "entry": "starter/crystal-a-positive-control-cannot-detect-a-yes-machine.md",
 "overlap": 0.006993006993006993}
```

**No act text and no essence text travels with a row.** So "recompute overlap from
the rows" is impossible in the naive sense — the fixture is a *value* fixture, not
an *input* fixture. What it does ship alongside is enough to rebuild every input:

- `acts` — all 16 act strings, verbatim;
- `synthetic_long_essence` — the full long synthetic essence;
- `essence_sha256` — sha256 of each of the 26 exact texts fed in;
- the 3 `starter/` crystals and the 21 `catalogue/` pages are **public** in the
  same repo (`tjonesit/crystals` @ `2918eb9`) and in `crystal-memory` @ `fe4e465`;
- `SYNTHETIC-unicode` text is fixed in the generator
  (`make-overlap-fixture.py:55`) and confirmed by its published sha256.

## 3. Input integrity — 26/26 hashes reproduce

I re-extracted all 26 essences independently (`crystal_registry._essence` for the
3 starter crystals, frontmatter-stripped bodies for the 21 catalogue pages, the
two synthetics as fixed) and hashed them:

```
essence sha256 agreement: 26/26 identical to fixture's published hashes
  input_kind labels agree: True
```

This matters: it proves I fed **the same inputs** as the package did, so the
416/416 output match is a comparison of like with like, not a coincidence.

## 4. Match rates — three-way

```
=== MATCH RATES (denominator = 416 rows) ===
MY implementation vs shipped      : 416/416 = 1.000000
PACKAGE fe4e465 vs shipped         : 416/416 = 1.000000
mine vs package identical (1e-12)  : 416/416
```

My implementation was written from the fixture's own `function` doc string
(found in the JSON, not in the source), i.e. independently of the code:

> "Jaccard over lowercase `\w{3,}` token sets, essence cut to its first 1500 chars
> BEFORE lowercasing; 0.0 if either side has no tokens"

Tolerance `1e-12` on doubles. **No row where I differ.**

## 5. The two separator rows behave as documented

`README.md:10-11` claims two rows exist specifically to separate a reimplementation
from the shipped one.

```
act_id=15 ('filler straddlin straddlingword beyondthecut') vs SYNTHETIC-long-essence:
    shipped 0.5            mine 0.500000      pkg 0.500000     -> "ours = 0.5" CONFIRMED
act_id=13 ('café naïve straße résumé') vs SYNTHETIC-unicode:
    shipped 0.4444444444   mine 0.444444      pkg 0.444444     -> "ours = 0.4444" CONFIRMED
```

**My own negative control** (the check that the fixture can actually fail): I
re-ran act 13 with an ASCII-only `\w` (`re.ASCII`) instead of Python's
Unicode-aware `\w`:

```
ASCII-\w control: act_id=15 vs SYNTHETIC-long-essence -> 0.5000  (shipped 0.5)       -- unchanged
ASCII-\w control: act_id=13 vs SYNTHETIC-unicode      -> 0.3750  (shipped 0.4444444) -- DIFFERS
```

So the Unicode discriminator is real and load-bearing: a reimplementation using
`re.ASCII` (or a non-Unicode tokenizer) **fails** exactly where he says it should,
at act 13, producing 0.3750 against the shipped 0.4444. The 1,500-char cut
discriminator (act 15) is a genuine control but it does **not** discriminate
against an ASCII-`\w` implementation — it only pins the cut. His README describes
act 13 as the Unicode pin, which is accurate.

## 6. Full regeneration — byte-for-byte

```
python lab/overlap-fixture-fe4e465/make-overlap-fixture.py <crystal-memory@fe4e465> regen.json
-> 416 rows (16 acts x 26 essences), 171 nonzero; commit fe4e4650 catalogue 8da5e640
```

```
regenerated == shipped, byte-for-byte JSON: True
row diffs: 0 of 416
acts identical: True
essence_sha256 identical: True
```

The fixture is fully reproducible from the public package plus the shipped script.

## 7. FINDING — the premise about our own reimplementation is FALSE

The brief says: *"our own reimplementation lives in
`D:\Project\_reference_repos\Tirthahq__crystal-memory__HEAD-6cb8479\scripts\crystal_act.py`
— check against that implementation, and note it is an OLDER tree than fe4e465."*

**That check is not possible, for a substantive reason — not a path or tooling problem:**

- Whole-tree grep for `overlap` in `Tirthahq__crystal-memory__HEAD-6cb8479` returns
  **2 hits, both prose**:
  - `scripts/crystal_registry.py:362` — `# overlap. It never enters the topic ranking, …` (a comment fragment)
  - `catalogue/a-check-written-with-the-code-inherits-its-assumptions.md:76` — the words "zero overlap" in an essay
- There is **no `def overlap`** anywhere in that tree. `crystal_act.py:57` has only
  the unrelated constant `FAT_ESSENCE = 1500`.
- `git log -S "def overlap" -- scripts/crystal_act.py` in `crystal-memory` returns
  exactly one commit: **`fe4e465` itself**.
- `git merge-base --is-ancestor 6cb8479 fe4e465` -> true;
  `git rev-list --count 6cb8479..fe4e465` -> **1**.

**So `6cb8479` is the direct parent of `fe4e465`, and `overlap()` was introduced by
`fe4e465` — the very commit the fixture pins.** There is no earlier version of this
function to compare against, by construction. Anyone following the brief's
instruction literally would find nothing and could not tell "wrong path" from
"wrong premise"; this file records the latter, verified.

Consequence for the audit: the overlap fixture is a **first-party self-consistency
check, not a third-party cross-check.** It verifies that the shipped numbers equal
what the shipped code computes — which I confirmed (416/416, plus byte-identical
regeneration) — but it cannot corroborate the function against an independent
prior implementation, because none exists upstream of `fe4e465`. I substituted a
genuinely independent path (my own implementation written from the published
doc string, §4) and it agrees.

## 8. Portability finding in the shipped generator (minor, in his favour to report)

`make-overlap-fixture.py:69` calls `out.write_text(...)` with **no `encoding=`** and
`ensure_ascii=False`. `pathlib.write_text` then uses the locale default encoding.
This machine's default is cp1251, and the document contains non-ASCII (é, ß), so
the shipped generator **crashes** here:

```
UnicodeEncodeError: 'charmap' codec can't encode character '\xe9' in position 9778
```

Run in a second environment mode (`PYTHONUTF8=1`, the §19.3 requirement to rule out
my own harness) it succeeds and reproduces the fixture exactly (§6). So the failure
is environmental, not a data defect — but the script as published only runs on a
UTF-8-default locale, which is worth knowing before anyone tries to regenerate it.

## 9. `NOT RE-DERIVABLE`

- **`NOT RE-DERIVABLE: the 2026-09-29 ordering measurements.** `make-overlap-fixture.py:6`
  states the 2026-09-29 ordering items carry private session content and are never
  shipped; they are absent by design and are **not** to be requested or reconstructed.
- **`NOT RE-DERIVABLE: production-replay behaviour of `overlap()`.**
  `README.md:8-9` is explicit that the 21 catalogue pages are *function* inputs only
  (they carry no essence markers; production overlap runs on private crystal
  essences), so the fixture does not exercise a production replay. Correctly
  scoped, and recorded here so the 416/416 is not over-read.
- **`NOT RE-DERIVABLE: the 215-item private overlap list** he declined to publish.
  Not attempted, and should not be: it carries raw session text. The public fixture
  is the correct substitute and is sufficient for the function check.