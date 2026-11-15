# ONNX dense build: where the 37 minutes went

- Date: 2026-11-12
- Base: `main` @ `a25627a`
- Machine: 12 logical CPUs, Windows
- Provider: `onnx:multilingual-e5-small-int8`, output 384-d
- Trigger: the dense build of this repository took **2 210.8 s for 7 307 chunks**
  (3.3 chunks/s) and was recorded as "not optimised".

## Question

Is the cost in the indexer, the HTTP layer, or the model — and is it fixable
without changing the answer?

## Measurements

### 1. Inference scales with sequence length (direct session, batch=32)

```
seq= 32 : 0.17 s  190.7 ch/s   6 103 tok/s
seq=128 : 0.86 s   37.1 ch/s   4 747 tok/s
seq=256 : 2.30 s   13.9 ch/s   3 569 tok/s
seq=512 : 6.33 s    5.1 ch/s   2 587 tok/s
```

The model is healthy: shorter inputs are up to 37x cheaper. Therefore a build
that costs the same for every chunk is padding every chunk to 512.

### 2. Before the fix, batch time did not depend on text length

```
32 x short  (~30 chars)   7.93 s   4.0 ch/s
32 x medium (~300 chars)  6.63 s   4.8 ch/s
32 x long   (~2000 chars) 6.21 s   5.2 ch/s
batch 8 / 16 / 32 / 64    4.2 / 5.1 / 5.2 / 4.6 ch/s   (no batch-size win)
```

Root cause in `src/core/embedder/onnx_server.py`: the tokenizer was configured
with `enable_padding(length=512)` and both `_embed_single` and `_embed_batch`
padded every input to `max_length` (512) before `session.run`. A 31-token chunk
paid for 512 tokens.

### 3. What the real corpus looks like (7 307 chunks)

```
total tokens      2 144 633
tokens min/median/p90/p99/max = 31 / 287 / 400 / 554 / 971
fixed 512 padding 3 741 184 padded tokens
dynamic, sorted batches ~2.18 M padded tokens
estimated embedding time: 1 450 s -> 679 s (2.13x)
```

The indexer already sorts chunks by length (`index_project_runner.py`,
`_flat_chunks.sort(key=lambda x: len(x[1]))`), so a per-batch maximum is very
close to the true lengths.

### 4. After the fix (per-batch padding)

```
32 x short   0.06 s   464 ch/s
32 x medium  0.63 s    50 ch/s
32 x long    6.16 s     5.2 ch/s   (unchanged, as expected)
```

Full rebuild of the same repository (fresh data root):

```
chunks 7 419   (main gained files since the first build)
wall   1 014.7 s   vs 2 210.8 s before   (2.18x)
```

Caveat: the "before" build ran with a full pytest suite in parallel for part of
its duration, so 2.18x is the wall-clock delta on this machine, not a clean A/B.
The clean evidence for the padding effect is the 0.06 s vs ~6.4 s short-batch
measurement and the 2.13x estimate on the corpus.

## Quality panel (frozen 48-query set)

Control: index built with fixed 512 padding, queries padded to 512.
Treatment: index built with per-batch padding, queries dynamic.
Both run the same hybrid `quality` path and the same text index; only the vector
table and the query padding differ.

```
control    n=48 hit@1=0.562 hit@5=0.688 MRR=0.601 p50=274ms
treatment  n=48 hit@1=0.583 hit@5=0.688 MRR=0.617 p50=258ms
paired: hit@1 +1/-0, hit@5 0/0 (33/48 both), MRR +2/-0
```

No query became worse; one moved into the top-1 and two improved in rank. The
panel is small, so this is "non-inferior on the frozen panel", not a general
quality claim. Command: `experiments/onnx_dense_2026_11/quality_panel.py
--arm control|treatment` with the matching `MSCODEBASE_DATA_DIR`.

## Correctness

Per-batch padding changes the tensor width, so quantised inference is not
bit-identical to fixed 512:

- same text, direct session: cosine 0.996 (12 tokens) / 0.998 (93 tokens);
- 7 059 identical chunks in two indexes: p50 0.998, p5 0.996, p1 0.925,
  min 0.863;
- same index, fixed-512 query vs dynamic query: top-1 file identical 14/15,
  overlap@5 = 0.48 (vector-only top-5 is unstable on adjacent chunks).

No retrieval-quality panel was run. `ONNX_FIXED_PADDING=512` restores the old
behaviour for deployments that must match an existing index exactly.

## Fix

- `src/core/embedder/onnx_server.py`: pad to the longest text **in the batch**;
  keep truncation at 512; `ONNX_FIXED_PADDING` (default 0) restores fixed width.
- Guard: `tests/test_onnx_dynamic_padding.py` (3 cases: per-batch max, truncation,
  legacy toggle).
- Verified: dense `smoke_e2e` PASSED (4 checks, step 4 = vector, provider=onnx,
  dim=384, results=3).

## Follow-ups

1. ~~Run the search-quality panel on a dynamic-padding index before making it
   the only mode~~ — done: hit@5 33/48 in both arms, no losing query.
2. Warm/cold build caching: a full rebuild still recomputes every chunk; the
   incremental path already skips unchanged files.
3. Consider length-bucketed batching in the indexer instead of sorting by chars
   (token-aware), which would tighten batch maxima further.
4. The 48-query panel is small; re-run `experiments/bench_2026_11` on a larger
   corpus before removing `ONNX_FIXED_PADDING` from the compatibility surface.
