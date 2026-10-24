# SUMMARY — trap-verify audit @ `2918eb9` / `450ddf2`

Deterministic verification. **No LLM call was made at any point.** No commits, no
pushes, no modification of any git tree. The only writes outside scratch were the
five files of this directory.

Both target commits verified to exist before anything was read:

```
2918eb9ad47526abb19a2976def6ba691873bdd0  2026-10-06T22:12:44Z
450ddf22d8ef1a2385b16c1dbd1386c73329030d  2026-10-06T19:59:03Z
3eecc40641b5c16c3b01848d8ff2517dcbda5b3c  2026-10-06T17:47:46Z  (prior bundle)
```

They are linearly ordered (`2918eb9 -> 450ddf2 -> 3eecc40`), so one checkout
covers both directories.

## (a) Did both headline numbers re-derive? — YES, both, exactly

| | claimed | re-derived (his code) | re-derived (my independent path) |
|---|---|---|---|
| **E1** point | -0.3056 | **-0.3056** | **-0.3055555556** |
| **E1** 95% CI | [-0.5, -0.1111] | **[-0.5, -0.1111]** | **[-0.5000000000, -0.1111111111]** |
| **E1** verdict | SUPPORT | SUPPORT | — |
| **E2 C3** point | -0.5455 | **-0.5455** | **-0.5454545455** |
| **E2 C3** CI (Bonferroni 98.33%, 11 tasks) | [-0.8485, -0.2727] | **[-0.8485, -0.2727]** | **[-0.8484848485, -0.2727272727]** |
| **E2 C3** verdict | SUPPORT | SUPPORT | — |

Exact commands (his recipe, `RUNS-AND-FIXTURES.md:18-22`):

```
cp analysis-deps/lablib.py prereg/analysis-code/
python prereg\analysis-code\analyse_e1.py --results runs\e1\results.jsonl
python prereg\analysis-code\analyse_e2.py --a runs\e2a\results.jsonl --b runs\e2b\results.jsonl
```

Run from a clean directory containing only those 6 files. Full detail:
`REDERIVE_2918eb9.md`.

**Component counts, re-derived: HELPFUL 18/35 = 0.5143, SHAM 30/35 = 0.8571** —
both confirmed. **Is 35 (not 36) the right denominator? Yes.** 36 is the run count
(12 traps x 3 reps, exactly, verified); 35 is the *approached* count, because
exactly one valid run per arm did not approach (`helpful-refuse` t5a rep 2,
`sham-refuse` t1a rep 1). The primary outcome is "hit **given** the run approached",
so 35 is the correct denominator and 36 would have been a defect. Note the 3
`peeked` voids are **not** the cause of 35 — they are excluded and their
replacements retained, restoring all three arms to 36 runs.

**Row counts 111 / 223 / 114 confirmed by actual count.** All three are banked-row
counts *including* voids; analysable rows are 108 / 216 / 108, matching
12x3x3, 12x6x3 and 12x3x3 exactly. "111 banked rows" is true and is not an
inflated denominator — the 3 extras are voided peeked attempts kept beside their
replacement, so three cells hold 4 rows.

Also re-derived and matching: "effect in 6 of the 12 traps, no trap got worse"
(exactly 6 negative, 6 zero, 0 positive); SHAM-vs-NONE +0.0278 [-0.1389, +0.1667];
E2 C1 = -0.0556 and C2 = -0.1111, both INCONCLUSIVE (CIs cross zero, as claimed).

## (b) Independent cross-check — AGREE, to 10 decimal places

Two independently written paths, no shared code:

- my validity rule vs his shipped `lablib.py`: **0 mismatches over all 448 rows**;
- E1 point -0.3055555556 (both paths); E1 CI [-0.5000000000, -0.1111111111] (both);
- E2 C3 point -0.5454545455 (both); CI [-0.8484848485, -0.2727272727] (both).

**No disagreement — reported as a negative result, not dressed up.** Both estimates
are exact rationals (-11/36 and -6/11), so the published 4-dp values are the
estimator rounded correctly, not a sampling artefact.

One honest limit: the **point estimates** are fully independent; the **bootstrap
CIs** agree only because I re-implemented his documented algorithm (same seed, same
10 000 draws, same percentile indices). That is a spec reproduction, not an
independent inference. Stated so the agreement is not over-read.
Detail: `CROSSCHECK_2918eb9.md`.

## (c) Overlap fixture — 416/416, denominator 416, zero mismatches

| check | result |
|---|---|
| Row count 416 | **CONFIRMED** (16 acts x 26 essences) |
| **My independent implementation vs shipped** | **416 / 416 = 1.000000** |
| Package `overlap()` @ `fe4e465` vs shipped | **416 / 416** |
| Shipped generator re-run verbatim | **byte-for-byte identical JSON** |
| Essence inputs identical (sha256) | **26 / 26** |
| **Rows where I differ** | **none — empty list, no row id to report** |
| Non-zero rows | 171 / 416 (so the match is not a table of zeros) |

Both pins verified: `package_commit fe4e465…` and `catalogue_tree 8da5e640…`
reproduced from `Tirthahq/crystal-memory` independently.

**Which the rows carry:** rows hold only `act_id`, `entry`, `overlap` — **no act text
and no essence text**. The inputs are recoverable from `acts`,
`synthetic_long_essence`, `essence_sha256`, the two synthetics fixed in the
generator, and the public `starter/` + `catalogue/` files — which is how I rebuilt
all 26 and confirmed them by hash.

**Both discriminator rows behave as documented, and my own negative control fires:**

```
act 15 vs SYNTHETIC-long-essence : shipped 0.5      mine 0.500000   -> 1500-char cut pinned
act 13 vs SYNTHETIC-unicode      : shipped 0.444444 mine 0.444444   -> Unicode \w pinned
ASCII-only \w control, act 13    : 0.3750  vs shipped 0.444444        -> DISCRIMINATES
ASCII-only \w control, act 15    : 0.5000  vs shipped 0.5             -> does not discriminate
```

So the fixture can genuinely fail: an ASCII-`\w` reimplementation breaks at act 13.

**FINDING — the brief's premise about our own reimplementation is false.** It says
our reimplementation lives in
`…Tirthahq__crystal-memory__HEAD-6cb8479\scripts\crystal_act.py`. It does not.
Whole-tree grep for `overlap` in that tree returns **2 hits, both prose**
(`crystal_registry.py:362` comment; one catalogue essay line); there is **no
`def overlap` anywhere**. `git log -S "def overlap"` returns exactly one commit —
**`fe4e465` itself** — and `git rev-list --count 6cb8479..fe4e465` = **1**, so
`6cb8479` is its direct parent. **The function was introduced by the very commit
the fixture pins**, so no prior independent implementation exists to check against.
The fixture is a first-party self-consistency check, not a third-party one. I
substituted a genuinely independent path (my own implementation written from the
published doc string) and it agrees 416/416.

Detail: `OVERLAP_FIXTURE_450ddf2.md`.

## (d) Privacy findings — no leak; one wording defect

**No leak.** 13-pattern sweep over the 63 new files: **0** host paths
(Windows, `/home`, `/Users`, `/var/folders`, `/private/tmp`, `ws-<hex>`),
**0** usernames, **0** API keys/tokens, **0** Anthropic session UUIDs, **0**
`<!-- crystal:essence -->` markers, **0** crystal essence text.

All three declared redactions verified field by field:

- `record`: 448/448 rows under `<lab>/runs/<cell>/` (0 residue);
- `session_id`: 448 rows -> **448 distinct** values, every one exactly 12 lowercase
  hex, **1:1 with `run_id`** so "rows stay joinable" holds;
- sandbox paths: `<ws>` appears 9x, **only** inside `peek_matches[].action`.

**The one finding, immaterial as a leak but real as wording:**
`RUNS-AND-FIXTURES.md:15` says a scan for "host paths, usernames, keys and emails
returned zero hits". **Three emails do ship:**

```
fixture/queues/mail.json:4   "ops@example.invalid"
fixture/queues/mail.json:8   "audit@example.invalid"
standins/svc.py:527         release@example.invalid
```

All three are RFC 2606 `.invalid` placeholders in a simulated mail queue — cannot be
real addresses. So the claim is true only under an unstated reserved-TLD filter, and
a reader running a naive regex gets 3 hits and may conclude the scan never ran. I
measured the sweep's FP rate before publishing any number (0/3 false positives
here, against 89% measured on our own repo on 2026-10-03), and I report the
per-hit judgement rather than the bare count.

Benign, named so they are not re-litigated: `tirtha` (26 hits) is the fictional
product name of the simulated workspace (`fixture/app/config.py:4`,
`fixture/deploy/tirtha.service:6-7`), already disclaimed at `README.md:94-96`; the
single `/Users/` hit is a **leak detector inside a stand-in tool**
(`standins/box_python.py:93`), i.e. the guard, not the leak.

Biggest privacy positives: **no crystal essence text ships** (only opaque
`k*.md` filenames), no bulk text dump anywhere (longest line in the four new
directories is 1399 chars = one JSON row), and the 16 rows carrying
`peek_matches` agent text are exactly the 16 rows the harness already flagged as
peeked/void.

**Not committed, per §7.1a/§20.1-20.2** — not because it leaks but because
third-party content is a licensing/publication hazard even when clean. Detail:
`PRIVACY_2918eb9.md`.

## (e) Paths written

Scratch (throwaway, outside every repo):

```
%LOCALAPPDATA%\mscodebase\audit-cache\trap-verify\
  tree_2918eb9.json          crystals-e1e2\   (clone @ 2918eb9)
  crystals-ov\               (clone @ 450ddf2)
  cm-fe4e465\                (clone of Tirthahq/crystal-memory @ fe4e465)
  rederive\                  the 6 files of his recipe
  regen.json                 generator re-run output
  indep.py ovcheck.py privscan.py residual.py denom.py wtree.py
```

Results (the only writes to your repo):

```
D:\Project\wt-audit-corrections\experiments\trap_rescore\results\
  INVENTORY_2918eb9.md        (new)
  REDERIVE_2918eb9.md         (new — SUPERSEDES the "not re-derivable" verdict in REDERIVE.md)
  CROSSCHECK_2918eb9.md       (new)
  OVERLAP_FIXTURE_450ddf2.md  (new)
  PRIVACY_2918eb9.md          (new)
  SUMMARY_2918eb9.md          (new, this file)
```

Pre-existing `INVENTORY.md`, `PREREG_CHECK.md`, `REDERIVE.md` were **not touched**
— the supersession is recorded as a new file per §19.11 (stable-ID supersede chain,
no silent edit of a published verdict). `frozen/` untouched. No git commit, no push.

## Everything I could NOT run, and why

- **`NOT RE-DERIVABLE: the N-version claim "approach agreed on 380 of 380 banked
  runs; hit agreed on 11 of 12 traps"** (`README.md:65-68`). `scorers_independent.py`
  and `compare_builds.py` need a `Run` object from the full harness; the bundle ships
  only the 35-line validity excerpt, and the README itself says the scorers are "here
  to be read and compared, not executed". No per-run tool-call transcripts ship, so
  the scorers cannot be run at all. Not checked, not refuted.
- **`NOT RE-DERIVABLE: t5a's post-hoc cross-check basis** (6/6 agreement on a later
  re-run with work directories kept, `README.md:66-68`) — those per-run files are
  not shipped.
- **`NOT RE-DERIVABLE: the 215-item private overlap list.** Deliberately not
  requested: it carries raw session text. The public fixture is the correct
  substitute and suffices for the function check.
- **`NOT RE-DERIVABLE: production-replay behaviour of `overlap()`.** The 21 catalogue
  pages carry no essence markers, so they are function inputs only — his
  `README.md:8-9` is correct to say so. I record it so 416/416 is not over-read.
- **`NOT RE-DERIVABLE: pre-redaction rows** (see (d)) — substitution unobservable,
  only the clean post-state is verifiable.
- **`NOT CHECKED: result commit `54cbcb19`** and the four pre-registration lock
  commits (`372d76af`, `b92088de`, `96cb9f92`, `28aa66cd`) — all in the private
  source repository, not reachable in `tjonesit/crystals`.
- **Environment note (not a data defect):** the shipped `make-overlap-fixture.py`
  crashes on this machine because `write_text()` at line 69 omits `encoding=` while
  the document contains non-ASCII and the locale default is cp1251. Confirmed
  environmental by re-running with `PYTHONUTF8=1`, which reproduced the fixture
  byte-for-byte (§19.3 two-mode requirement).

## One-line bottom line

Both headline intervals, both component counts, all three row counts, the 35-vs-36
denominator, and all 416 overlap rows re-derive exactly under an independently
written path; the only defects found are one imprecise sentence in his privacy-pass
note ("zero" email hits vs 3 RFC-2606 placeholders), one portability bug in his
generator, and one stale premise in *my own brief* about where our reimplementation
lives.