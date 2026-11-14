---
title: "My Benchmark Said 'No Change' Three Times. It Was Reading a Cache Committed to Git."
published: false
description: "0.2 minutes, identical numbers. My harness resumed from a 71-row capture in git. Cleared, the same panel reads 19 → 32 → 38 across five code states, and one list slice accounts for the whole gap."
tags: devtools, testing, python, ai
cover_image: https://raw.githubusercontent.com/ManSio/mscodebase-intelligence/main/docs/blog/assets/benchmark-cache-cover.png
---

> **Part 5 of: [MSCodeBase Intelligence — Field Notes](https://github.com/ManSio/mscodebase-intelligence/tree/main/docs/blog)** — *[Part 1: PageRank](https://dev.to/mansio/i-measured-pagerank-token-savings-on-a-real-codebase-the-result-will-surprise-you-5bnj) · [Part 2: Silent Vector Contamination](https://dev.to/mansio/the-silent-vector-contamination-bug-why-your-concurrent-embeddings-might-be-lying-to-you-5fg7) · [Part 3: Verify-on-Read](https://dev.to/mansio/the-mechanical-vs-the-semantic-what-happens-when-ai-memory-is-wrong-38ko) · [Part 4: Bootstrap Pipeline](https://dev.to/mansio/from-a-test-suite-trace-to-a-search-signal-the-bootstrap-pipeline-story-407b) · Part 5*

> **TL;DR:** my benchmark printed the same numbers for four days because it was resuming from a 71-row capture file committed to git. With the cache cleared, the same panel on the same machine reads **19 → 32 → 38** across five code states. The number I published as a design trade-off was a disk read — and the fix that closes the gap is a two-item list slice.

![A terminal that says "resuming: 71 tasks already captured" next to 19 → 38 and "0.2 min vs 6.1 min"](https://raw.githubusercontent.com/ManSio/mscodebase-intelligence/main/docs/blog/assets/benchmark-cache-cover.png)

## What I set out to test

I build MSCodeBase, an MCP server that indexes a repository and answers questions about the code. The claim behind it is narrow and testable: *it finds things grep can't.*

The benchmark asks it to localize a commit. The query is the commit message, the gold is `git show --name-only` — the files that commit actually touched — and the corpus is a worktree frozen at a base commit, so the fix being searched for is not in the index. Three corpora: my own repo frozen at `7c2c7a3`, plus `psf/requests` and `sqlalchemy`, which I did not write.

The panel is 174 commits in `(B, HEAD]`. 66 tasks whose answer files were created *after* `B` are unsolvable by construction — dropped, and counted, so the denominator stays visible. 108 solvable, split 71 dev / 37 sealed by date. The panel hash is in `MANIFEST.sha256` and it has not changed through any of this.

Four arms, same corpus, same base:

| arm | what it is |
|---|---|
| `tool` | the product as it ships |
| `tool + neighbours` | the same call with `include_neighbours=true` — the refusal bypassed |
| `search` | the BM25/hybrid channel alone, the baseline that matters |
| `grep` | message words against file contents, the floor |

## What I measured on 10 November

The dev split, 71 solvable tasks:

| arm | hit@1 | hit@5 | any@8 |
|---|---:|---:|---:|
| tool (default) | 12 | **19** | 23 |
| tool + neighbours | 24 | 37 | 44 |
| search channel alone | 10 | 24 | 29 |
| grep (floor) | 0 | 2 | 6 |

Both pre-registered bars failed, in the gate's own words: **P1 FAIL (default 0.268 < 0.35)** and **P2 FAIL (default is 5 below plain search on dev)**.

So I did what a benchmark owner should do: I classified the misses. All 52 of them:

```plaintext
36  abstain, zero rows     -> names in the message do not exist in the corpus
11  outside top-8
 4  rank 6-8
 1  outside top-8 (answer)
```

**36 of 52 were refusals**, not bad ranking and not a chunking artefact. The gate took the first identifier it extracted from the commit message, found zero occurrences of that token, and withheld the eight neighbours it had already computed.

## The conclusion I published

The refusal is a policy I chose on purpose: **never present an unverified row as an answer.** A commit message names things the commit *introduces*; an API that did not exist in the corpus at `B` cannot occur in it. The gate was doing exactly what it was built to do, and the benchmark was cold about it, because a refusal does not help a reader find the file.

So I wrote this:

> This is a policy decision (honesty vs recall), not a ranking defect.

And the report priced it: **-33 tasks of 108 solvable** (dev 19 vs 38, sealed 7 vs 21). Then the same 19 went into a log entry that said "`identical`" before and after a fix, and into another that said "19/71 **both ways**".

One run on 10 November. Three publications after it. Zero re-runs.

It is a satisfying sentence. It says: my tool is not worse, it is *honest*, and honesty costs recall. It is also exactly what you write when the alternative — that your gate is broken — would require deleting a paragraph you have already published.

## The run that took 0.2 minutes

On 14 November I re-ran the panel. It finished in **0.2 minutes** and printed every digit from four days earlier.

The harness resumes. That is a feature — a run that dies at task 16 should not start over — and it is implemented the obvious way:

```python
partial = HERE / f"results_{args.split}.partial.jsonl"
done = set()
if partial.is_file():
    for line in partial.read_text(encoding="utf-8").splitlines():
        old = json.loads(line); rows.append(old); done.add(old["id"])
    print(f"resuming: {len(done)} tasks already captured")
for task in tasks:
    if task["id"] in done:
        continue
```

Note the `print`. The harness told me, in plain text, on line three of its own output: **`resuming: 71 tasks already captured`**. I read the table at the bottom and skipped the sentence at the top. That is the whole failure, and it is not subtle.

`results_dev.partial.jsonl` is tracked in git (commit `e033edc`), 71 rows, one per task. Every clone and every fresh checkout started with November's answers already "captured", and `run.py` faithfully skipped the work and printed them back.

I did not notice for four days, because the numbers looked *stable*. Stable is exactly what a cache is.

## Three reads of one panel

Same machine, same index, same 71 tasks, cache cleared where it says so:

| what was measured | tool hit@5 | wall clock |
|---|---:|---:|
| captured rows from 10 Nov, replayed on HEAD | 19 | 0.2 min |
| code at `deb5ff4` (11 Nov), cache cleared | **32** | 6.1 min |
| HEAD (14 Nov), cache cleared | **38** | 6.1 min |

![Bar chart: tool hit@5 on the dev panel at five points, 19 cached rows, 32 at deb5ff4, 32 after the wording fix, 38 after the identifier fix, 38 at HEAD](https://raw.githubusercontent.com/ManSio/mscodebase-intelligence/main/docs/blog/assets/benchmark-cache-bars.png)

The first row is the tell. **19 came from a file, not from a run.** The same HEAD code that scores 38 in six minutes scores 19 in twelve seconds, because twelve seconds is how long it takes to read 71 answers off a disk.

Paired at hit@5, task by task: cached rows vs `deb5ff4` — **13 up, 0 down**; `deb5ff4` vs HEAD — **6 up, 0 down**.

I have to stop that sentence there, because it is only true at hit@5. At `any@8` one task does go down between `deb5ff4` and HEAD, and on `sqlalchemy` one commit that used to be found is no longer found. There is no run in this post where nothing regressed; there are runs where the *headline metric* did not.

The control arms did not move at all: `search` 11/22/29 and `grep` 0/2/6 in all three reads, task by task identical. Whatever moved, moved in the tool's own gate, not in retrieval.

## The four ways the gate was wrong

The gate is one small thing: if no identifier from the question occurs in the corpus, print "not found" instead of a neighbour list. Four defects in that path:

1. **A Gerrit `Change-Id` counted as an identifier** (`3a3f46a`). A 40-character hash never occurs in source, so every `sqlalchemy` commit carrying one was refused. `0 → 11` of 40.
2. **The refusal was decided by the first token** (`deb5ff4`). On commit prose that token is an annotation: `_orm.registry=0` next to `Declarative=785`. 13 of 40 commits answered nothing while the rows existed. `11 → 17`.
3. **The warning called a real hit a neighbour** (`b9f91c4`). Before the fix above, the branch was unreachable; after it, the message printed "the results below are neighbours, not matches" over an exact match. The policy was honest and the text explaining it was not.
4. **The grep channel counted two identifiers out of four** (`f3b0cc4`). `_identifiers()` returns up to `_MAX_IDS = 4`; the loop took `identifiers[:2]`. A name in slot 3 or 4 that *did* occur could not stop the refusal, so the answer was emptied while the file that answers it sat in the index.

Two of the four shipped with a test that failed first: slots 1–2 as a control (pass both ways), slots 3–4 failing on the old code and passing after; and `test_recovered_answer_is_not_called_neighbours`. For the other two I have the commit message and the before/after number, not a red test, and I am not going to claim otherwise.

Defect 3 changes no score at all — it only changes what the tool says. It is in this list because a gate that lies in its output is the same bug as a gate that lies in its ranking, and it took a reviewer to see it.

## What the external repos say

Two repositories I did not write. No cache here — the external runner rebuilds every task from git, every run:

| | `psf/requests` (25) | `sqlalchemy` (40) |
|---|---:|---:|
| tool at `deb5ff4` | 12 | 17 (twice) |
| tool at HEAD | **13** | **18** |
| search channel (control) | 15 | 18 |
| grep (floor) | 19 | 20 |

`deb5ff4` reproduces the November numbers exactly — 12 and 17, the values in my facts file, and 17 twice in two control runs.

The +1 on `requests` is one task up and none down. The +1 on `sqlalchemy` is **two up and one down** — a commit the old gate found is now missed — and the rejects are not individually explained.

grep still wins on both, 19 vs 13 and 20 vs 18. That is a ranking gap. It is not a cache, it is not a policy, and I have not fixed it.

## What each fix is actually worth

The first version of this post said I could not attribute the +19. Then I ran the intermediate commits: cold cache, same machine, same index, same day, 71 tasks each, none of them resumed.

| point | what changed in the product | tool hit@5 | wall clock |
|---|---|---:|---:|
| cached rows | nothing — a replay of 10 Nov | 19 | 0.2 min |
| `deb5ff4` | hashes are not identifiers; refusal needs *no* identifier | **32** | 13.5 min |
| `b9f91c4` | the warning stops calling a real hit a neighbour | 32 | 7.7 min |
| `f3b0cc4` | the grep channel counts all four identifiers, not two | **38** | 7.7 min |
| HEAD | + ONNX batch padding, + vector-schema width | 38 | 6.1 min |

Read it as a decomposition:

- **The wording fix is worth zero**, which is exactly what it should be: it changes what the tool says, not which rows it returns. A message-only change that moved the score would have been a bug in the benchmark.
- **The identifier fix is worth all six tasks.** `identifiers[:2]` was throwing away answers that the third or fourth name in the message would have justified.
- **The two retrieval commits are worth zero here.** ONNX batch padding and vector-schema width cannot move a text-index panel, and they didn't.
- **The 13 tasks between the cached rows and `deb5ff4` belong to the two November gate fixes as a pair.** Splitting them costs two more runs of six minutes; I did not do it, so they stay a pair.

That is the whole trade-off I published, at the bottom of a list slice.

## What the policy actually costs

The `19` and the `38` are not the same kind of thing, and that is the second reason this is hard to write. At HEAD the honest arm and the bypass arm are the same number:

```plaintext
dev, HEAD (n=71)      hit@1  hit@5  any@8   MRR
tool (abstain on)        23     38     43   0.416
tool + neighbours        23     38     44   0.417
search channel           11     22     29   0.239
grep                      0      2      6   0.051
```

**hit@5 identical, `any@8` differs by one task.** That is the measured cost of the refusal policy: one task in seventy-one. The report's -33 was measured against the 10 November code and does not describe what ships today.

`one task` and `eighteen` are not the same claim, and I have published both in the last four days.

## Reproduce

One panel, one command per point. The cache is opt-in now, so a cold run is the default:

```bash
git worktree add ../wt-<full-sha> <full-sha>   # deb5ff4, b9f91c4, f3b0cc4
python experiments/bench_2026_11/run.py --split dev
```

Two guards before you trust the output:

1. `resuming:` must not appear anywhere in it. If it does, you are reading a file, not a run.
2. Anything under three minutes did not execute 71 tasks.

The panel is frozen: `tasks.jsonl` hashes to `71395d45…`, the first line of `MANIFEST.sha256`, and the corpus is a worktree at `7c2c7a3`. On Windows, hash the blob, not the checkout — `core.autocrlf` will give you a different digest and make it look like the panel changed:

```bash
git show HEAD:experiments/bench_2026_11/tasks.jsonl | git hash-object --stdin
```

The external arms need no capture at all: `external.py` rebuilds every task from `git log` and `git show` on each run, which is why they are the part of this benchmark that cannot lie to me.

## Red Team

- **The dev panel is not held out.** The gate defects were found on `sqlalchemy` and in code review, then measured on dev. The +13 and the +6 are in-sample.
- **My harness's noise floor is one task.** Two identical control runs at `deb5ff4`, cache cleared both times, gave the neighbours arm 37 and then 38 at hit@5. The tool arm held at 32. So ±1 is noise, and the +1 on each external repo sits exactly on that floor.
- **Environment is not fully excluded.** Both control runs fell back to a degraded ONNX path ("server did not start in 60s"); the HEAD run did not. The search arm is identical everywhere, which suggests retrieval was untouched — but "suggests" is the word, and I did not get a HEAD run under fallback.
- **The 19 was a real measurement once.** It describes the product on 10 November. It was never a measurement of the code I shipped on 11 November, and both facts are true at the same time.
- **CIs overlap.** 32/71 is [0.34, 0.57], 38/71 is [0.42, 0.65]. The paired direction is what carries the claim, not the interval.
- **n=25 on `requests`.** One task is four percentage points. The +1 there is the smallest possible effect — it could be luck.
- **A committed cache is a reproducibility landmine.** Anyone who clones this repo and runs the harness gets my November answers, in 0.2 minutes, with a `resuming` line they can read past just as easily as I did.

## What I changed

The harness now refuses to replay itself. Reuse is opt-in:

```text
python experiments/bench_2026_11/run.py --split dev            # runs all 71 tasks
python experiments/bench_2026_11/run.py --split dev --resume   # continues a dead run
```

Without `--resume` the stale capture is printed and dropped, because `run.py` appends to it and an appended run would silently mix two products. There is a test for that behaviour, and it fails when the flag is removed — I checked by removing it.

## What I'd do differently

Read a run's first line before its last table. If it finished in twelve seconds, it did not run.

The rest is downstream of that: my benchmark is not dishonest. It did exactly what it was told — skip the work you already have. I told it, in a file, in git, and then read its output as a measurement of today.

**Does your benchmark resume from a capture? When did you last delete it?**

---

## Acknowledgments

A huge thank you to everyone who engages with these posts in the comments. Your feedback, real-world observations, counter-examples, and benchmark numbers directly shape these experiments. This kind of open technical critique is what keeps engineering honest.

---

## A note on how this was written

Every experiment, bug, failure, and idea here is mine — I earned them the hard way, in production, in public. AI worked as my editor: it helped me structure thoughts and polish my English. It did not invent the facts, because it has none of its own.

No AI detectors were consulted in the making of this disclosure. They have enough trouble agreeing on what I am.

---

> **Disclaimer & Status:** draft (source-material for the article). This is not a "feature advertisement", but an honest engineering story: figures are reproducible, weak points are named, and unaddressed risks are listed in the "Red Team" and "What I cannot attribute" sections.

*Raw artifacts: `experiments/bench_2026_11/` — the captured rows (`results_dev.partial.jsonl`, 71, commit `e033edc`), the fresh run outputs, both external result files and `REPORT.md`. The control ran in a worktree at `deb5ff4`; the panel hash in `MANIFEST.sha256` was unchanged, so no task was re-barred. Invalid runs, the old cache and the failed gates sit on disk next to the passing ones.*
