---
title: "The 60x Slowdown Bug: Why token_type_ids Kills Your Embedding Performance"
published: true
description: "How passing token_type_ids to OpenVINO INT8 models causes a 60x performance regression without any errors — and how to detect it with A/B benchmarking."
tags: machinelearning, python, openvino, embeddings
cover_image: 
---

> **TL;DR:** If you pass `token_type_ids` to an INT8 quantized E5 model in OpenVINO, it runs **60x slower** (320 → 5 ch/s) without throwing any errors. The model works correctly — it just honestly computes a dead branch (NSP) for zero-valued tensors. Here's how we found it and how to avoid it.

---

## The Symptom

Our embedding pipeline was running at 5 chunks/second. We expected 300+.

The model loaded fine. The inference completed without errors. The output vectors were correct (cosine similarity ~1.0 with reference). But it was **painfully slow**.

---

## The Investigation

We suspected OpenVINO configuration, so we ran isolated benchmarks:

```python
# Benchmark: token_type_ids impact
import openvino as ov
import numpy as np

core = ov.Core()
model = core.read_model("model_quantized.onnx")
compiled = core.compile_model(model, "CPU")

# Without token_type_ids
input_no_tt = {
    "input_ids": np.zeros((1, 128), dtype=np.int64),
    "attention_mask": np.ones((1, 128), dtype=np.int64),
}
# Result: 2.9ms per inference = 348 ch/s

# With token_type_ids
input_with_tt = {
    "input_ids": np.zeros((1, 128), dtype=np.int64),
    "attention_mask": np.ones((1, 128), dtype=np.int64),
    "token_type_ids": np.zeros((1, 128), dtype=np.int64),  # All zeros!
}
# Result: 175ms per inference = 5.7 ch/s
```

**60x slowdown** from adding a zero-valued tensor.

---

## The Root Cause

E5 models have an NSP (Next Sentence Prediction) head that uses `token_type_ids`. When you pass all-zero `token_type_ids`:

1. OpenVINO **doesn't prune** the NSP branch (it sees a valid input tensor)
2. The model **honestly computes** NSP for the zero tensor
3. This adds ~172ms of unnecessary computation per inference

Without `token_type_ids`:
1. OpenVINO **prunes** the unused branch at compile time
2. Inference is pure embedding computation
3. Result: 2.9ms per inference

---

## Why This Is Dangerous

1. **No error thrown** — the model works correctly
2. **Output is valid** — vectors are semantically correct
3. **Only symptom is speed** — you might not notice if you don't benchmark
4. **Common mistake** — many tutorials pass all three inputs to BERT models

---

## The Fix

For E5-family models (E5-small, E5-base, multilingual-e5), **don't pass `token_type_ids`**:

```python
# WRONG: passes token_type_ids (60x slower)
inputs = {
    "input_ids": tokenized["input_ids"],
    "attention_mask": tokenized["attention_mask"],
    "token_type_ids": tokenized["token_type_ids"],  # Don't do this!
}

# CORRECT: only pass input_ids and attention_mask
inputs = {
    "input_ids": tokenized["input_ids"],
    "attention_mask": tokenized["attention_mask"],
}
```

---

## Detection: A/B Benchmark

If you suspect this issue, run this quick test:

```python
import time
import numpy as np

def benchmark_inference(compiled_model, input_data, n_runs=100):
    """Measure inference time with and without token_type_ids."""
    times = []
    for _ in range(n_runs):
        start = time.perf_counter()
        result = compiled_model(input_data)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
    return np.mean(times), np.std(times)

# Test without token_type_ids
mean_no_tt, std_no_tt = benchmark_inference(model, input_no_tt)
print(f"Without token_type_ids: {mean_no_tt:.1f}ms ± {std_no_tt:.1f}ms")

# Test with token_type_ids
mean_with_tt, std_with_tt = benchmark_inference(model, input_with_tt)
print(f"With token_type_ids: {mean_with_tt:.1f}ms ± {std_with_tt:.1f}ms")

# Check for 60x regression
ratio = mean_with_tt / mean_no_tt
if ratio > 10:
    print(f"WARNING: {ratio:.0f}x slowdown detected!")
    print("Solution: Remove token_type_ids from model inputs")
```

---

## Which Models Are Affected?

| Model | token_type_ids Impact | Recommendation |
|-------|----------------------|----------------|
| E5-small | **60x slower** | Don't pass |
| E5-base | **60x slower** | Don't pass |
| multilingual-e5 | **60x slower** | Don't pass |
| BGE-M3 | Normal | Can pass (uses NSP) |
| BERT-uncased | Normal | Can pass (uses NSP) |

The key: if your model was trained with NSP (Next Sentence Prediction), passing `token_type_ids` is required. If it wasn't (E5 family), passing it causes the slowdown.

---

## Key Takeaways

1. **Valid input ≠ Optimal input.** `token_type_ids` is a valid input, but passing it to E5 models causes 60x slowdown.

2. **Always benchmark.** Don't assume your inference pipeline is fast because it works correctly.

3. **Check your model's architecture.** E5 models don't use NSP, so `token_type_ids` is dead weight.

4. **OpenVINO is honest.** It computes what you ask for, even if it's useless. This is a feature, not a bug — but you need to know what you're asking for.

---

## Discussion

Have you encountered similar "silent performance regressions" in your ML pipelines? How do you benchmark inference speed in production?

---

*Part of my research on [MSCodeBase Intelligence](https://github.com/ManSio/mscodebase-intelligence) — an MCP server for codebase intelligence.*
