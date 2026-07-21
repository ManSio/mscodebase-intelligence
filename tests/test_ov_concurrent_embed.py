"""
Test: AsyncInferQueue concurrent embed_batch — no vector cross-contamination.

Regression test for the race condition found during architecture review
(2026-07-18): self._ov_results was shared across all embed_batch() calls,
so concurrent indexer + search threads could overwrite each other's
vectors with syntactically valid but semantically wrong embeddings.

Fix: each embed_batch() uses a local dict passed via userdata=(index, dict),
so concurrent calls are fully isolated.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class FakeAsyncInferQueue:
    """Simulates ov.AsyncInferQueue with configurable latency.

    The callback is called from a worker thread (like real OpenVINO),
    with the exact userdata that was passed to start_async().
    """

    def __init__(self, jobs=4, latency_ms=5):
        self.jobs = jobs
        self.latency_ms = latency_ms
        self._callback = None
        self._requests: list[tuple[dict, object]] = []

    def set_callback(self, cb):
        self._callback = cb

    def start_async(self, inputs, userdata):
        self._requests.append((inputs, userdata))

    def wait_all(self):
        """Simulate async completion: call callback from thread pool."""
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.jobs) as pool:
            futures = []
            for inputs, userdata in self._requests:
                futures.append(pool.submit(self._run_one, inputs, userdata))
            for f in futures:
                f.result()
        self._requests.clear()

    def _run_one(self, inputs, userdata):
        time.sleep(self.latency_ms / 1000)
        # Simulate a unique output per input (hash of input_ids as fingerprint)
        ids = inputs["input_ids"]
        # Deterministic "embedding" based on input content
        rng = np.random.RandomState(int(ids.sum()) % (2**31))
        vec = rng.randn(1, 384).astype(np.float32)
        # Normalize for cosine similarity tests
        vec = vec / (np.linalg.norm(vec, axis=-1, keepdims=True) + 1e-9)

        # Create a fake request object with get_output_tensor
        fake_request = MagicMock()
        fake_output = MagicMock()
        fake_output.data = [vec]
        fake_request.get_output_tensor.return_value = fake_output
        self._callback(fake_request, userdata)


def _make_embedder_with_fake_queue(texts_per_call=5):
    """Create a RemoteEmbedder wired to FakeAsyncInferQueue."""
    from src.providers.embedder.remote_embedder import RemoteEmbedder

    with patch.object(RemoteEmbedder, '__init__', lambda self: None):
        embedder = RemoteEmbedder()

    # Set up minimal state
    embedder.embedding_dim = 384
    embedder._max_embed_tokens = 128
    embedder.mode = "onnx"
    embedder._mode_lock = threading.Lock()
    embedder._onnx_last_used = 0

    # Fake tokenizer
    from unittest.mock import MagicMock as MM

    class FakeEnc:
        def __init__(self, text):
            # ids: unique fingerprint per text (so different texts → different vectors)
            self.ids = [hash(text) % 100000] * 10 + [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            self.attention_mask = [1] * len(self.ids)

    fake_tokenizer = MM()
    fake_tokenizer.encode_batch = lambda texts, **kw: [FakeEnc(t) for t in texts]
    embedder._tokenizer = fake_tokenizer

    # Fake OpenVINO state
    embedder._ov_compiled = MagicMock()
    embedder._ov_async_queue = FakeAsyncInferQueue(jobs=4, latency_ms=3)
    embedder._ov_has_token_type_ids = False
    embedder._ov_call_lock = threading.Lock()  # Variant B fix (P0-3)

    # Wire callback (same pattern as _init_openvino)
    def _ov_callback(request, userdata):
        idx, local_results = userdata
        out_tensor = request.get_output_tensor(0)
        local_results[idx] = out_tensor.data[0].copy()

    embedder._ov_async_queue.set_callback(_ov_callback)

    return embedder


class TestConcurrentEmbedIsolation:
    """Verify that concurrent embed_batch() calls don't cross-contaminate."""

    def test_single_call_results_match_indices(self):
        """Sanity: single embed_batch returns dict with correct indices."""
        embedder = _make_embedder_with_fake_queue()
        texts = ["alpha bravo charlie", "delta echo foxtrot", "golf hotel india"]
        results = embedder.embed_batch(texts, is_query=False)
        assert len(results) == 3
        # Each result should be a non-zero vector
        for r in results:
            assert isinstance(r, list)
            assert len(r) == 384
            assert any(v != 0.0 for v in r)

    @pytest.mark.asyncio
    async def test_concurrent_calls_no_cross_contamination(self):
        """5 concurrent embed_batch with different texts — no vector mixing."""
        embedder = _make_embedder_with_fake_queue()

        # Each call gets a unique set of texts (fingerprinted by prefix)
        call_texts = {
            0: [f"CALL_ZERO_text_{i}" for i in range(8)],
            1: [f"CALL_ONE_text_{i}" for i in range(6)],
            2: [f"CALL_TWO_text_{i}" for i in range(10)],
            3: [f"CALL_THREE_text_{i}" for i in range(4)],
            4: [f"CALL_FOUR_text_{i}" for i in range(7)],
        }

        results: dict[int, list] = {}

        def run_call(call_id):
            results[call_id] = embedder.embed_batch(call_texts[call_id], is_query=False)

        # Launch 5 concurrent calls from different threads
        threads = [threading.Thread(target=run_call, args=(cid,)) for cid in call_texts]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Verify: each call returned exactly as many results as it had texts
        for call_id, texts in call_texts.items():
            assert call_id in results, f"Call {call_id} did not complete"
            assert len(results[call_id]) == len(texts), (
                f"Call {call_id}: expected {len(texts)} results, "
                f"got {len(results[call_id])}"
            )

        # Verify: no zero vectors (would indicate lost result)
        for call_id, res_list in results.items():
            for i, r in enumerate(res_list):
                assert any(v != 0.0 for v in r), (
                    f"Call {call_id}, result {i}: zero vector — "
                    "callback result was lost or overwritten"
                )

    @pytest.mark.asyncio
    async def test_concurrent_vectors_belong_to_own_texts(self):
        """Cosine similarity: each result vector should match its OWN text,
        not a text from a concurrent call."""
        embedder = _make_embedder_with_fake_queue()

        # Two calls with VERY different texts (easy to distinguish)
        texts_a = ["python def class import async" for _ in range(5)]
        texts_b = ["banana mango cherry apple grape" for _ in range(5)]

        results_a = [None]
        results_b = [None]

        def call_a():
            results_a[0] = embedder.embed_batch(texts_a, is_query=False)

        def call_b():
            results_b[0] = embedder.embed_batch(texts_b, is_query=False)

        # Launch concurrently
        ta = threading.Thread(target=call_a)
        tb = threading.Thread(target=call_b)
        ta.start()
        tb.start()
        ta.join(timeout=10)
        tb.join(timeout=10)

        assert results_a[0] is not None
        assert results_b[0] is not None
        assert len(results_a[0]) == 5
        assert len(results_b[0]) == 5

        # Within each call, all vectors should be identical
        # (same text → same hash → same FakeAsyncInferQueue output)
        def cosine(a, b):
            a, b = np.array(a), np.array(b)
            return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

        # Intra-call consistency: vectors within same call should be very similar
        for i in range(1, 5):
            sim_a = cosine(results_a[0][0], results_a[0][i])
            sim_b = cosine(results_b[0][0], results_b[0][i])
            assert sim_a > 0.95, f"Call A: vectors 0 and {i} differ (cos={sim_a:.3f})"
            assert sim_b > 0.95, f"Call B: vectors 0 and {i} differ (cos={sim_b:.3f})"

        # Cross-call divergence: vectors from different calls should differ
        cross_sim = cosine(results_a[0][0], results_b[0][0])
        assert cross_sim < 0.5, (
            f"Cross-contamination detected: call_A[0] and call_B[0] "
            f"have cosine={cross_sim:.3f} (should be < 0.5 for different texts)"
        )

    def test_rapid_sequential_calls_no_state_leak(self):
        """100 rapid sequential calls — no leftover state between calls."""
        embedder = _make_embedder_with_fake_queue()

        prev_vectors = None
        for call_num in range(100):
            texts = [f"call_{call_num}_text_{i}" for i in range(3)]
            results = embedder.embed_batch(texts, is_query=False)
            assert len(results) == 3
            for r in results:
                assert any(v != 0.0 for v in r), f"Zero vector at call {call_num}"

            # Vectors should change between calls (different texts → different hashes)
            if prev_vectors is not None:
                # At least one vector should differ from previous call
                changed = any(
                    not np.array_equal(np.array(results[i]), np.array(prev_vectors[i]))
                    for i in range(min(len(results), len(prev_vectors)))
                )
                assert changed, f"Call {call_num}: vectors identical to previous call (state leak?)"
            prev_vectors = results
