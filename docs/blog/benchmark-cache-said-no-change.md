---
title: "My Benchmark Said 'No Change' Three Times. It Was Reading a Cache Committed to Git."
published: false
tags: devtools, testing, python, ai
description: "0.2 minutes, identical numbers: my harness resumed from a 71-row capture in git. Cleared, the same panel reads 19 → 32 → 38, and I cannot credit a single fix for it."
---

On 14 November my code-search benchmark finished in **0.2 minutes** and printed exactly the numbers from four days earlier — every digit, all four arms.

It was reading a cache. The cache is committed to my repository.

Clearing it, on the same machine, same index, same 71 tasks, same commit: **6.1 minutes**, and the tool's score went from 19 to 38.

This post is about the three verdicts I published in between, and about the attribution I am not going to make at the end.

## The run that took 0.2 minutes

I build MSCodeBase, an MCP server that indexes a repository and answers questions about the code. The benchmark asks it to localize a commit: the query is the commit message, the gold is `git show --name-only`, and the corpus is a worktree frozen at a base commit so the fix is not in the index.

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

`results_dev.partial.jsonl` is tracked in git (commit `e033edc`), 71 rows, one per task. Every clone and every fresh checkout starts with November's answers already "captured", and `run.py` faithfully skips the work and prints them back.

I did not notice for four days, because the numbers looked *stable*. Stable is exactly what a cache is.

## What I had already published

The report came first, on 10 November, and it priced my refusal policy at **-33 tasks of 108 solvable** (dev 19 vs 38, sealed 7 vs 21). Then the same 19 went into a log entry that said "`identical`" before and after a fix, and into another that said "19/71 **both ways**".

One run on 10 November. Three publications after it. Zero re-runs.

The sentence I built on top of it felt like a finding:

> This is a policy decision (honesty vs recall), not a ranking defect.

It says: my tool is not worse, it is *honest*, and honesty costs recall. It is also exactly what you write when the alternative — that your gate is broken — would require deleting a paragraph you have already published.

## Three reads of one panel

| what was measured | tool hit@5 | wall clock |
|---|---:|---:|
| cache from 10 Nov, resumed on HEAD | 19 | 0.2 min |
| code at `deb5ff4` (11 Nov), cache cleared | **32** | 6.1 min |
| HEAD (14 Nov), cache cleared | **38** | 6.1 min |

The first row is the tell. **19 came from a file, not from a run.** The same HEAD code that scores 38 in six minutes scores 19 in twelve seconds, because twelve seconds is how long it takes to read 71 answers off a disk.

Paired at hit@5, task by task: cached rows vs `deb5ff4` — **13 up, 0 down**; `deb5ff4` vs HEAD — **6 up, 0 down**.

I have to stop that sentence there, because it is only true at hit@5. At `any@8` one task does go down between `deb5ff4` and HEAD, and on `sqlalchemy` one commit that used to be found is no longer found. There is no run in this post where nothing regressed; there are runs where the *headline metric* did not.

The control arms did not move at all: `search` 11/22/29 and `grep` 0/2/6 in all three reads, and task-by-task identical.

## The four ways the gate was wrong

The gate is one small thing: if no identifier from the question occurs in the corpus, print "not found" instead of a neighbour list. Four defects in that path:

1. **A Gerrit `Change-Id` counted as an identifier** (`3a3f46a`). A 40-character hash never occurs in source, so every `sqlalchemy` commit carrying one was refused. `0 → 11` of 40.
2. **The refusal was decided by the first token** (`deb5ff4`). On commit prose that token is an annotation: `_orm.registry=0` next to `Declarative=785`. 13 of 40 commits answered nothing while the rows existed. `11 → 17`.
3. **The warning called a real hit a neighbour** (`b9f91c4`). Before the fix above, the branch was unreachable; after it, the message printed "the results below are neighbours, not matches" over an exact match. The policy was honest and the text explaining it was not.
4. **The grep channel counted two identifiers out of four** (`f3b0cc4`). `_identifiers()` returns up to `_MAX_IDS = 4`; the loop took `identifiers[:2]`. A name in slot 3 or 4 that *did* occur could not stop the refusal, so the answer was emptied while the file that answers it sat in the index.

Two of the four shipped with a test that failed first: slots 1–2 as a control (pass both ways), slots 3–4 failing on the old code and passing after; and `test_recovered_answer_is_not_called_neighbours`. For the other two I have the commit message and the before/after number, not a red test, and I am not going to claim otherwise.

Defect 3 changes no score at all — it only changes what the tool says. It is in this list because a gate that lies in its output is the same bug as a gate that lies in its ranking, and it took a reviewer to see it.

## What I cannot attribute

Here is where this post refuses to give me a clean ending.

`19 → 32` is not one fix. The range from the cached code to `deb5ff4` contains **five** src commits, including a ranking change (production modules named `test_*.py`) and a hint-wording change. `32 → 38` contains **seven**, including two retrieval-side commits — ONNX batch padding and a vector-schema width fix — that have nothing to do with the refusal gate.

So the honest statement is: **the panel moved by +19 across two code ranges, and I did not isolate any single commit inside them.** The two gate fixes are documented as worth `0 → 11` and `11 → 17` on `sqlalchemy`, where the harness does not cache and each fix was measured on its own. On the dev panel I can only report the endpoints.

If I wanted per-fix credit I would have had to run each intermediate commit on a cold cache, in one environment, on the same day. That is four more runs of six minutes. I did not do it, and a number I cannot split is a number I do not get to use for credit.

## Three economies, one panel

The `19` and the `38` are not the same kind of thing, and that is the second reason this is hard to write:

| | dev, hit@5 | dev, `any@8` |
|---|---:|---:|
| tool (refusal on) | 38 | 43 |
| tool + neighbours (refusal bypassed) | 38 | 44 |

At hit@5 the policy now costs **nothing**. At `any@8` it costs **one task in seventy-one**. The report's −33 was measured against the 10 November code and does not describe what ships today.

`one task` and `eighteen` are not the same claim, and I have published both in the last four days.

## What the external repos say

Two repositories I did not write. No cache here — the external runner rebuilds every task from git, every run:

| | `psf/requests` (25) | `sqlalchemy` (40) |
|---|---:|---:|
| tool at `deb5ff4` | 12 | 17 (twice) |
| tool at HEAD | **13** | **18** |
| search channel (control) | 15 | 18 |
| grep (floor) | 19 | 20 |

`deb5ff4` reproduces the November numbers exactly — 12 and 17, the values in my facts file.

The +1 on `requests` is one task up and none down. The +1 on `sqlalchemy` is **two up and one down** — a commit that the old gate found is now missed — and the rejects are not individually explained. grep still wins on both, 19 vs 13 and 20 vs 18, and that is a ranking gap I have not fixed and cannot blame on a cache.

## Red Team

- **The dev panel is not held out.** The gate defects were found on `sqlalchemy` and in code review, then measured on dev. The +13 and +6 are in-sample.
- **My harness's noise floor is one task.** Two identical control runs at `deb5ff4`, cache cleared both times, gave the neighbours arm 37 and then 38 at hit@5. The tool arm held at 32. So ±1 is noise, and the +1 on each external repo sits exactly on that floor.
- **Environment is not fully excluded.** Both control runs fell back to a degraded ONNX path ("server did not start in 60s"); the HEAD run did not. The search arm is identical everywhere, which suggests retrieval was untouched — but "suggests" is the word, and I did not get a HEAD run under fallback.
- **The 19 was a real measurement once.** It describes the product on 10 November. It was never a measurement of the code I shipped on 11 November, and both facts are true at the same time.
- **CIs overlap.** 32/71 is [0.34, 0.57], 38/71 is [0.42, 0.65]. The paired direction is what carries the claim, not the interval.
- **n=25 on `requests`.** One task is four percentage points. The +1 there is the smallest possible effect — it could be luck.
- **A committed cache is a reproducibility landmine.** Anyone who clones this repo and runs the harness gets my November answers, in 0.2 minutes, with a `resuming` line they can read past just as easily as I did.

## What I'd do differently

Make resume opt-in (`--resume`), and drop `results_*.partial.jsonl` from version control. Then the rule I am writing down now, having failed it:

> If a run finishes suspiciously fast, read its first line before its last table.

My benchmark is not dishonest. It did exactly what it was told: skip the work you already have. I told it, in a file, in git, and then read its output as a measurement of today.

**Does your benchmark resume from a capture? When did you last delete it?**

---

*Every experiment, bug, failure, and idea here is mine — I earned them the hard way, in production, in public. AI worked as my editor: it helped me structure thoughts and polish my English. It did not invent the facts, because it has none of its own. No AI detectors were consulted in the making of this disclosure. They have enough trouble agreeing on what I am.*

*Raw artifacts: `experiments/bench_2026_11/` — the captured rows (`results_dev.partial.jsonl`, 71, commit `e033edc`), the fresh run outputs, both external result files and `REPORT.md`. The control ran in a worktree at `deb5ff4`; the panel hash in `MANIFEST.sha256` was unchanged, so no task was re-barred. Invalid runs, the old cache and the failed gates sit on disk next to the passing ones.*
