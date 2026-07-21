---
title: "The Silent Vector Contamination Bug: Why Your Concurrent Embeddings Might Be Lying to You"
published: true
description: "How a subtle race condition in async inference queues returned syntactically valid embeddings for the wrong inputs — and how to catch it with a cosine contamination test."
tags: machinelearning, python, rag, openvino
cover_image: 
---

> **TL;DR:** If you run concurrent inference (e.g., via OpenVINO `AsyncInferQueue` or custom threading) for text/code embeddings, your tests might show `0 exceptions` and `0 errors`, while silently returning embeddings belonging to *other* inputs in the batch. Here is how we caught a subtle race condition using a cosine-similarity contamination test.

---

## The Setup

We use OpenVINO with an INT8 quantized [E5-small](https://huggingface.co/keisuke-miyako/multilingual-e5-small-onnx-int8) model for in-process code embedding. To maximize throughput on multi-core CPUs, we set up an asynchronous inference queue (`AsyncInferQueue`) with `jobs=4`.

In standard unit testing, everything looked pristine:
- All infer jobs completed with exit code 0
- No `None` values or zero-filled tensors were returned
- Latency and throughput were great (~37 chunks/sec on Ryzen 5600)

However, during end-to-end RAG retrieval tests, we noticed weird semantic anomalies: searching for authentication logic would occasionally return chunks related to database migrations or UI components with unreasonably high confidence.

---

## The Bug: Silent Contamination

The root cause was a subtle race condition in callback/userdata mapping inside the async wrapper.

Because the inputs were processed concurrently across multiple execution streams, a shared user-data context wasn't strictly isolated per inference request. When Request A (`auth.py`) and Request B (`payment.py`) were scheduled back-to-back:

1. Both requests succeeded without throwing exceptions
2. The output tensor for Request A was mapped to the metadata/chunk wrapper of Request B
3. The resulting vector was **syntactically valid and non-zero**, but it represented the *wrong text input*

Standard assertion tests like `assert output_vector is not None` or `assert output_vector.shape == (384,)` passed 100% of the time. The pipeline was silently corrupting the vector store.

### The Code

```python
# Before fix: shared results dict across concurrent calls
self._ov_results = {}

def _callback(request, userdata):
    # BUG: userdata is a global index (0, 1, 2, ...)
    # Two concurrent calls reuse the same indices!
    self._ov_results[userdata] = request.get_tensor().data
```

The problem: `userdata` was a simple integer counter (`0, 1, 2, ...`) that reset between `embed_batch` calls. When two calls overlapped, they wrote to the same dictionary keys.

---

## The Solution: Cosine Contamination Testing

To catch this reliably in CI, we wrote an explicit **cross-contamination test** designed for concurrent embedding queues.

### The Test Logic

```python
import asyncio
import numpy as np
import pytest

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

@pytest.mark.asyncio
async def test_async_embedder_no_cross_contamination(embedder):
    """Verify that concurrent embedding doesn't cross-contaminate vectors."""
    
    # 1. Semantically distinct inputs
    samples = {
        "auth": "def authenticate_user(username, password_hash): return verify_jwt(token)",
        "sql": "SELECT u.id, u.email FROM users u JOIN orders o ON u.id = o.user_id WHERE o.status = 'active'",
        "html": "<div class='flex-container'><span id='user-profile'>Profile View</span></div>",
        "rust": "pub fn allocate_buffer(size: usize) -> Result<Vec<u8>, MemoryError> { Vec::with_capacity(size) }"
    }

    # 2. Sequential baseline (ground truth)
    baseline_vectors = {}
    for key, text in samples.items():
        baseline_vectors[key] = await embedder.embed_single_sync(text)

    # 3. High-concurrency stress test with randomized queue order
    async_tasks = []
    keys_order = list(samples.keys()) * 10  # 40 concurrent requests
    np.random.shuffle(keys_order)

    for key in keys_order:
        async_tasks.append(embedder.embed_async(samples[key]))

    async_results = await asyncio.gather(*async_tasks)

    # 4. Verify identity & cross-isolation via Cosine Similarity
    for expected_key, async_vec in zip(keys_order, async_results):
        # Self-similarity against ground truth must be ~1.0
        self_sim = cosine_similarity(async_vec, baseline_vectors[expected_key])
        assert self_sim > 0.98, (
            f"Contamination detected! Vector for '{expected_key}' drifted "
            f"(sim={self_sim:.2f}, expected >0.98)"
        )

        # Cross-similarity against distinct inputs must remain low
        for other_key, other_vec in baseline_vectors.items():
            if other_key != expected_key:
                cross_sim = cosine_similarity(async_vec, other_vec)
                assert cross_sim < 0.6, (
                    f"Cross-talk detected between '{expected_key}' and "
                    f"'{other_key}' (sim={cross_sim:.2f}, expected <0.6)"
                )
```

### Benchmark Results

Running this test on the **unpatched** queue revealed the contamination:

| Metric | Unpatched | Patched | Expected |
|--------|-----------|---------|----------|
| Self-similarity (auth↔auth) | **0.34** ❌ | 0.99 ✅ | >0.98 |
| Cross-similarity (auth↔sql) | **0.98** ❌ | 0.32 ✅ | <0.6 |
| Exceptions thrown | 0 | 0 | 0 |
| Zero tensors | 0 | 0 | 0 |

The unpatched queue showed **0 exceptions** while vectors were completely swapped.

---

## The Fix

The fix was simple once we understood the problem:

```python
# After fix: isolated results per call
self._ov_results = {}

def _callback(request, userdata):
    # FIX: userdata is now (index, local_results_dict)
    # Each embed_batch call creates its own dict
    index, local_dict = userdata
    local_dict[index] = request.get_tensor().data
```

Each `embed_batch` call now creates its own isolated dictionary. The callback writes to the call-specific dict, not a shared global. No locks needed — complete isolation by design.

---

## Key Takeaways

1. **`0 exceptions` ≠ Correctness.** Silent data corruption doesn't throw errors.

2. **Valid shape ≠ Valid embedding.** A `(384,)` tensor with non-zero floats can represent the wrong input.

3. **Write cross-contamination tests.** If you use async inference queues or multi-threading for vector generation, verify that Vector X actually belongs to Input X under concurrent load.

4. **Cosine similarity is your friend.** A simple similarity check between concurrent outputs and sequential baselines catches contamination that no other test detects.

---

## How to Run This Test

```bash
# Clone the repo
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence

# Install dependencies
pip install -e ".[dev]"

# Run the contamination test
pytest tests/test_ov_concurrent_embed.py -v
```

---

## Discussion

Has anyone else bumped into silent cross-talk in ONNX Runtime, OpenVINO, or TensorRT async queues? How do you validate thread isolation in your embedding pipelines?

---

*Built with [MSCodeBase Intelligence](https://github.com/ManSio/mscodebase-intelligence) — an MCP server for codebase intelligence with incident memory and root cause prediction.*
