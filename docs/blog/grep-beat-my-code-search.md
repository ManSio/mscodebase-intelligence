---
title: "grep Beat My Code Search on 19 of 25 Commits. The Bug Was in My Own Gate."
published: false
tags: devtools, python, testing, ai
description: "Three corpora, two of them repositories I did not write: grep won both, 36 of 52 misses were refusals, and two bugs in my own refusal gate were hiding answers."
---

I build MSCodeBase, an MCP server that indexes a repository and answers questions about the code. The quiet claim behind it was simple: *it finds things grep can't.*

On 10 November I stopped testing that claim on panels I wrote myself. Three corpora instead: my own repository with the index frozen at a base commit (so the fixes being searched for are not in it), and two repositories I did not write — `psf/requests` and `sqlalchemy`.

grep won on both of the repos I did not write: **19 of 25 commits** on `requests`, **20 of 40** on `sqlalchemy`.

Then I opened the misses. The number was right and my explanation for it was wrong: **my tool was refusing to answer.**

This post is the 48 hours between those two sentences.

## The test that removed my excuses

Every earlier panel was authored by me. That is a fair objection, and "tuned to the test" is not an insult — it is a description of how benchmarks rot.

So this time the **question** is a commit message, the **gold** is `git show --name-only` — which files that commit actually touched — and the **corpus** is pinned at a base commit, so the fixes are not in the index and nothing is hand-picked.

Panel: 174 commits in `(B, HEAD]` of my own repo, corpus at `B = 7c2c7a3` (2026-09-06). 66 tasks whose answer files were created *after* `B` are unsolvable by construction — dropped, and counted, so the denominator stays visible. 108 solvable, split 71 dev / 37 sealed by date. The sealed half ran once.

Four arms, same corpus, same base, dev split (n=71):

| arm | hit@1 | hit@5 | any@8 |
|---|---:|---:|---:|
| tool (default) | 12 | 19 | 23 |
| tool + neighbours | 24 | 37 | 44 |
| search channel alone | 10 | 24 | 29 |
| grep (floor) | 0 | 2 | 6 |

Both pre-registered bars failed, in the gate's own words: **P1 FAIL (default 0.268 < 0.35)** and **P2 FAIL (default is 5 below plain search on dev)**.

I wrote the verdict into the log the same day: *the default answers less than plain search.*

## 36 of 52

The verdict was true and the diagnosis was wrong. So I did the only thing a benchmark owner can do — count what the misses actually were.

The report classifies all 52 dev misses at hit@5:

```plaintext
36  abstain, zero rows     -> names in the message do not exist in the corpus
11  outside top-8
 4  rank 6-8
 1  outside top-8 (answer)
```

**36 of 52 were refusals**, not bad ranking and not a chunking artefact. The gate took the **first** identifier it extracted from the commit message, found zero occurrences of that token, and withheld the eight neighbours it had already computed.

The reason is a policy I chose on purpose: **never present an unverified row as an answer.** A commit message names things that *the commit introduces* — an API that did not exist in the corpus at `B` cannot occur in it. The gate is correct on this panel. The panel is correct. The product is doing exactly what it was built to do, and the benchmark is cold about it: a refusal does not help the reader find the file.

```plaintext
abstain: no identifier from this message occurs in the corpus
next: investigate(query="...", include_neighbours=true, limit=8)
```

On those same 52 tasks with the neighbour list switched back on, the default goes from 0 to 18 hits at hit@5 — which is where **19 → 37 of 71** comes from. This is a policy decision — honesty versus recall — not a ranking defect. I am not going to pretend otherwise in either direction.

## Then the refusals turned out to be buggy

Here is where it gets uncomfortable. The policy was honest. The implementation of the policy was not.

**First bug.** On `sqlalchemy` the tool scored **0 of 40**. Not "poorly" — zero. `_identifiers` took the 40-character Gerrit `Change-Id` hash as the first identifier, the gate counted zero occurrences of a hash in source files, and every commit carrying one was refused.

Hashes and commit trailers are not code names. Both are out now; `close` stayed, because it is a real method name. The score went **0 → 11 of 40**.

**Second bug, found by the rerun of a different experiment.** With the hash fix in, 13 of those 40 commits still answered nothing while the rows existed. `_abstains` decided "the subject does not occur" from the **first** extracted identifier. On commit prose that token is an annotation or a type name: `_orm.registry=0` next to `Declarative=785`.

```plaintext
sqlalchemy, 40 commits            hit@5
  before both fixes                 0
  after the Change-Id fix          11    (E71)
  after the first-token fix        17    (bar >=15: PASS)
```

The fix is one sentence: refuse only when **no** identifier occurs. Of the 13 formerly-empty commits, the code comment says 8 had been hiding the gold; 6 recovered; the other 2 are dropped by the evidence gate, which I have not investigated.

The same fix on `psf/requests`: **10 → 12 of 25**, and no arm lost a task.

So the honest sequence is not "my tool is worse than grep". It is: *my tool was worse than grep, partly because my gate was broken — and I cannot yet say how much of the rest is policy.*

## The bar I could not reach, because I set it wrong

Pre-registered: of the 13 formerly-empty commits, recover at least 8. Result: **6 of 13. Failed.**

I could have quietly re-run the gate with a different threshold. Here is why I did not.

The bar of 8 came from an `include_neighbours=true` run — the arm that *bypasses* the refusal, while the change under test *keeps* it. Two of the thirteen are the all-zero case and must stay refused, so the reachable maximum for this change is 11 of 13; two more sit behind the separate evidence gate I just mentioned. The gate was calibrated against a different product than the one being measured.

The frozen rule said "P4 < 8 → revert". Its premise — "the first-token rule is not the cause" — is contradicted by P1 (+6 tasks, no leak). So the gate is recorded as **failed** and not re-edited, and the ship decision sits with me, labelled as a decision.

A bar derived from the wrong arm is a hidden tie-break. If I fix the bar after seeing the results, every other number in this post becomes optional too.

## What did not work

**File-level dedup.** Hypothesis: grep ranks whole files, my tool answers with chunks, and 22–29% of answer rows repeated a file already shown. So I added `MSCODEBASE_FILE_DEDUP=file`: one row per file first, leftovers fill the tail.

The duplicates obeyed: on the same 20 commits they went **25 → 0**, and 10 of those repeats were sitting at ranks 1–5, so the swaps were real. The score did not move — **11 of 40 either way**, against a bar of 14. Worse, the flag broke the thing it was least supposed to touch: usage probes kept **5 of 20**, against a bar of 15 of 20.

Negative result. The switch stays experimental and off, documented as such in all three `CONFIGURATION.md` files. "Dedup by file" must never be cited as the explanation for the grep gap, because it is not one.

**A denominator bug, caught before publishing.** My first draft of that section said "6 of 20". The count came from the unfiltered raw-commit sample, which includes docs-only commits whose empty answer is *correct*. The script now applies the benchmark task filter and refuses to print a share on a different denominator than the panel.

**A production module demoted for its name.** Same week, a different experiment: the tool ranked `src/core/test_impact.py` — a module that *predicts* test impact — as a test file, because its path matched `test_*.py`. Its definitions lost 2.0 rank on code questions, and three tasks failed *while a plain grep found them*. Blast radius: 926 `.py` files, 271 matched the pattern; of the ones the experiment classified, 260 were real tests and **1 was a production module**. Classification is now content-based outside `tests/`; targeted recheck went 0/9 → 9/9 at top-1.

## What survives

grep beats the tool at commit localization on both external repos: `psf/requests` **19 vs 12** of 25, `sqlalchemy` **20 vs 17** of 40. That is now a row in the repository's facts file, in the same table as the numbers I like.

The requests arm, in full:

| arm | hit@1 | hit@5 |
|---|---:|---:|
| grep | 6 | 19 |
| search channel | 5 | 15 |
| tool + neighbours | 9 | 13 |
| tool (before the fixes) | 8 | 10 |
| tool (after the fixes) | 9 | 12 |

What does survive is the other half of the contract: on 44 fabricated-name tasks the tool answers **0 of 44**. Silent, no leak. That is the number I care about more than any hit@k on this panel — a tool that refuses when it does not know is worth less than grep on recall, and on that panel it is more careful than grep about what it does not know.

One more, because it is the most useful single number in the run: default **19 of 71** with refusals counted as misses, and **37 of 71** when the refusal prints the next call and you follow it. The 18-task gap is the cost of my honesty policy, measured on the same panel.

## Red Team: the attacks that drew blood

- **The grep baseline is biased down, and still wins.** It reads corpus files by path from `ls-files`, so files created after the base are empty for it. That handicap makes the result *stronger*, not weaker — and I still cannot call it a general claim about small repos.
- **n=25 on `requests`.** One task is 4 points at hit@5, and with that n the intervals are wide enough to touch: the log prints tool [0.23, 0.59] (the pre-fix arm) and grep [0.57, 0.89], overlapping at 0.57–0.59. Direction, with intervals printed.
- **The log and the experiment report disagree by one or two tasks.** The report's re-run gives `neighbours` 38 and `search` 22 on dev where the log says 37 and 24, which moves "5 below search" to 3. I quote the log, because that is the entry with the verdict in it — and I am telling you rather than picking the nicer number.
- **One repo, one base, per claim.** Two external repos are two data points, not a law.
- **The sealed arm ran once.** Re-running it until it looks better is how a sealed split stops being sealed.
- **The harness died twice**, at 16 and 22 tasks, with no traceback. The runner now resumes from `results_*.partial.jsonl` instead of restarting the arm.
- **Refusals counted as misses.** Fair to a reader, unfair to a ranker. Both numbers are printed so you can choose your own denominator.
- **Two rows still unexplained.** The evidence gate drops 2 of the 13 formerly-empty commits; I have not investigated. It is in the log as not investigated, not as fixed.

## The boring lesson

A benchmark that measures your product's *policy* while you read it as a measure of its *quality* will make you fix the wrong thing for as long as you don't count your misses. Mine did. The fix was not a better ranker — it was two bugs in a gate, a negative result I kept, and a bar I refused to move after the fact.

If your tool can refuse to answer, hit@k is not one number. On this panel mine are 19 of 71 with refusals as misses and 37 of 71 with the refusal followed; on a separate negative panel, 0 of 44 fabricated names answered. What are yours?

---

*Every experiment, bug, failure, and idea here is mine — I earned them the hard way, in production, in public. AI worked as my editor: it helped me structure thoughts and polish my English. It did not invent the facts, because it has none of its own. No AI detectors were consulted in the making of this disclosure. They have enough trouble agreeing on what I am.*

*Raw logs: `EXPERIMENTS_LOG.md` entries E67–E73, plus `experiments/bench_2026_11/REPORT.md` for the per-split tables and the miss classification. External numbers: `docs/FACTS.md` §7. Invalid runs and failed gates are on disk next to the passing ones; nothing was re-run until it looked good.*
