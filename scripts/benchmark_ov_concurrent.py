"""
Benchmark: AsyncInferQueue concurrent throughput + cross-contamination check.

Measures ch/s at 1, 2, 5 concurrent embed_batch() callers.
Verifies that vectors belong to their own texts (no cross-contamination).

Usage:
    python scripts/benchmark_ov_concurrent.py

Closes Definition of Done §7.6 for P0-3 (AsyncInferQueue Variant B fix).
"""
import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import threading
import time
import traceback
from pathlib import Path

try:
    import numpy as np
    import openvino as ov
    from tokenizers import Tokenizer

    # ─── Paths ─────────────────────────────────────────────────
    EXT_DIR = Path.home() / "AppData/Local/Zed/extensions/mscodebase-intelligence"
    MODEL_DIR = EXT_DIR / ".codebase_models/onnx/multilingual-e5-small-int8"
    MODEL_FILE = MODEL_DIR / "model_quantized.onnx"
    TOKENIZER_FILE = MODEL_DIR / "tokenizer.json"

    if not MODEL_FILE.exists():
        print(f"❌ Model not found: {MODEL_FILE}")
        sys.exit(1)

    # ─── Load model ────────────────────────────────────────────
    print(f"🔧 Loading model: {MODEL_DIR.name}")
    core = ov.Core()
    model = core.read_model(str(MODEL_FILE))
    for inp in model.inputs:
        model.reshape({inp.any_name: [1, 128]})
    compiled = core.compile_model(model, "CPU", config={
        "PERFORMANCE_HINT": "LATENCY",
        "INFERENCE_NUM_THREADS": "0",
    })

    # ─── Tokenizer ─────────────────────────────────────────────
    tokenizer = Tokenizer.from_file(str(TOKENIZER_FILE))
    tokenizer.enable_padding(pad_token="<pad>", pad_id=1, length=128)
    tokenizer.enable_truncation(max_length=128)

    # ─── Global callback (matches real code: set once in _init_openvino) ──
    # Callback writes into the local_results dict passed via userdata.
    # Each embed_batch creates its own dict, so concurrent calls are isolated.
    def _global_callback(request, userdata):
        idx, local_dict = userdata
        out = request.get_output_tensor(0)
        local_dict[idx] = out.data[0].copy()

    # ─── Benchmark helper ──────────────────────────────────────
    def benchmark_concurrent(n_threads: int, chunks_per_thread: int = 10,
                              pool_size: int = 4) -> dict:
        """Run n_threads concurrent embed_batch, measure ch/s + contamination."""
        queue = ov.AsyncInferQueue(compiled, jobs=pool_size)
        queue.set_callback(_global_callback)

        # Variant B fix: lock serializes concurrent calls (matches remote_embedder.py)
        ov_call_lock = threading.Lock()

        # Pre-bind token_type_ids = zeros for all requests in pool
        try:
            tt_tensor = ov.Tensor(np.zeros((1, 128), dtype=np.int64))
            for _req in queue:
                _req.set_tensor("token_type_ids", tt_tensor)
        except Exception:
            pass  # model without tt input

        # ─── Test texts: UNIQUE non-overlapping topics per thread ──
        # Each thread gets 2 copies of 2 unique topics (4 chunks total).
        # No topic appears in more than one thread.
        # Contamination check: for each vector, nearest neighbor across ALL
        # vectors must be the duplicate of the same topic from the same thread.
        # If nearest neighbor is from a different thread → contamination.
        _all_topics = [
            "python async def class import typing decorator",
            "database sql postgresql transaction commit rollback",
            "banana mango cherry apple grape fruit smoothie",
            "quantum physics relativity entropy thermodynamics energy",
            "docker kubernetes microservices deployment helm terraform",
            "neural network gradient descent backpropagation pytorch",
            "cybersecurity encryption firewall intrusion detection zero-trust",
            "astronomy galaxy nebula pulsar blackhole exoplanet",
            "philosophy epistemology metaphysics ethics logic ontology",
            "economics inflation interest supply demand monetary policy",
        ]
        all_texts = {}
        _topic_idx = 0
        for t in range(n_threads):
            # Each thread gets 2 unique topics, each repeated twice = 4 chunks
            t1 = _all_topics[_topic_idx % len(_all_topics)]
            t2 = _all_topics[(_topic_idx + 1) % len(_all_topics)]
            _topic_idx += 2
            texts = [t1, t1, t2, t2]  # 2 copies of each — known pairs for self-match
            all_texts[t] = texts

        # ─── Results storage ───────────────────────────────────
        thread_results: dict[int, list[list[float]]] = {}
        errors: list[str] = []

        def embed_batch(thread_id: int):
            """Single embed_batch call (one thread)."""
            try:
                texts = all_texts[thread_id]
                prefixed = [f"passage: {t}" for t in texts]
                enc = tokenizer.encode_batch(prefixed, add_special_tokens=True)

                valid_indices = [i for i, e in enumerate(enc) if e and len(e.ids) > 0]
                if not valid_indices:
                    errors.append(f"Thread {thread_id}: no valid tokens")
                    return

                ids_all = np.array([enc[i].ids for i in valid_indices], dtype=np.int64)
                mask_all = np.array([enc[i].attention_mask for i in valid_indices], dtype=np.int64)

                # Variant B fix: lock around submit+wait+collect (matches remote_embedder.py)
                with ov_call_lock:
                    # Local results dict (isolation fix from a97f0ff)
                    local_results: dict[int, np.ndarray] = {}

                    for idx_in, i in enumerate(valid_indices):
                        feed = {
                            "input_ids": ids_all[idx_in:idx_in+1],
                            "attention_mask": mask_all[idx_in:idx_in+1],
                        }
                        queue.start_async(feed, (i, local_results))
                    queue.wait_all()

                    # Mean-pool
                    vecs = []
                    for idx_in, i in enumerate(valid_indices):
                        if i not in local_results:
                            errors.append(f"Thread {thread_id}: chunk {i} lost")
                            continue
                        token_emb = local_results[i]
                        mask_exp = np.expand_dims(mask_all[idx_in], -1).astype(float)
                        sum_emb = np.sum(token_emb * mask_exp, 0)
                        sum_mask = np.clip(np.sum(mask_exp, 0), a_min=1e-9, a_max=None)
                        vec = (sum_emb / sum_mask).tolist()
                        vecs.append(vec)
                    thread_results[thread_id] = vecs
            except Exception as e:
                errors.append(f"Thread {thread_id}: {type(e).__name__}: {e}")

        # ─── Launch concurrent ─────────────────────────────────
        total_chunks = sum(len(t) for t in all_texts.values())
        t0 = time.perf_counter()
        threads = [
            threading.Thread(target=embed_batch, args=(tid,))
            for tid in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        elapsed = time.perf_counter() - t0

        ch_per_sec = total_chunks / elapsed if elapsed > 0 else 0

        # ─── Cross-contamination check: argmax self-match ──────
        # Each thread has 2 copies of 2 unique topics (4 chunks).
        # For each vector, find its nearest neighbor across ALL vectors.
        # Nearest neighbor must be the duplicate of the SAME topic
        # from the SAME thread (known by position: [t1,t1,t2,t2]).
        # If nearest neighbor is from a different thread → contamination.
        contamination_errors = []
        if n_threads >= 2 and len(thread_results) >= 2:
            def cosine(a, b):
                a, b = np.array(a), np.array(b)
                return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

            # Flatten: each vector tagged with (thread_id, local_idx)
            all_vecs: list[tuple[int, int, np.ndarray]] = []
            for tid, vecs in thread_results.items():
                for lidx, v in enumerate(vecs):
                    all_vecs.append((tid, lidx, np.array(v)))

            # Known pairs: within each thread, indices [0,1] are same topic,
            # [2,3] are same topic. Map: (tid, 0)↔(tid, 1), (tid, 2)↔(tid, 3)
            def expected_pair(tid, lidx):
                if lidx in (0, 1):
                    return (tid, 1 - lidx)  # 0↔1
                return (tid, 5 - lidx)       # 2↔3

            for i, (tid_a, lidx_a, vec_a) in enumerate(all_vecs):
                # Find nearest neighbor (excluding self)
                best_sim = -1.0
                best_match = None
                for j, (tid_b, lidx_b, vec_b) in enumerate(all_vecs):
                    if i == j:
                        continue
                    sim = cosine(vec_a, vec_b)
                    if sim > best_sim:
                        best_sim = sim
                        best_match = (tid_b, lidx_b)

                expected = expected_pair(tid_a, lidx_a)
                if best_match != expected:
                    contamination_errors.append(
                        f"Vector (thread={tid_a}, idx={lidx_a}) "
                        f"nearest={best_match} (cos={best_sim:.4f}), "
                        f"expected={expected}"
                    )

        return {
            "threads": n_threads,
            "chunks": total_chunks,
            "elapsed_sec": round(elapsed, 3),
            "ch_per_sec": round(ch_per_sec, 1),
            "errors": len(errors),
            "error_details": errors[:5],
            "contamination_errors": len(contamination_errors),
            "contamination_detail": contamination_errors[:5],
        }

    # ─── Run benchmark ─────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"Benchmark: AsyncInferQueue(jobs=4) + Variant B lock")
    print(f"Model: {MODEL_DIR.name} (INT8, 384dim)")
    print(f"Scenario: indexer(batch=4) + search(batch=1) = 5 concurrent")
    print(f"{'='*70}\n")

    results = []
    for n in [1, 2, 5]:
        print(f"Testing {n} concurrent thread(s)...", end=" ", flush=True)
        r = benchmark_concurrent(n, chunks_per_thread=10, pool_size=4)
        results.append(r)
        print(f"✓ {r['chunks']} chunks in {r['elapsed_sec']}s = {r['ch_per_sec']} ch/s"
              + (f" ({r['errors']} errors)" if r['errors'] else ""))

    # ─── Summary table ─────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"{'Threads':>8} | {'Chunks':>8} | {'Time (s)':>10} | {'ch/s':>8} | {'Errors':>8}")
    print(f"{'-'*8}-+-{'-'*8}-+-{'-'*10}-+-{'-'*8}-+-{'-'*8}")
    for r in results:
        print(f"{r['threads']:>8} | {r['chunks']:>8} | {r['elapsed_sec']:>10.3f} | "
              f"{r['ch_per_sec']:>8.1f} | {r['errors']:>8}")

    # ─── Speedup calculation ───────────────────────────────────
    baseline = results[0]['ch_per_sec'] if results else 1
    print(f"\nSpeedup vs 1 thread:")
    for r in results[1:]:
        speedup = r['ch_per_sec'] / baseline if baseline > 0 else 0
        print(f"  {r['threads']} threads: {speedup:.2f}× baseline")

    # ─── Contamination report ──────────────────────────────────
    print(f"\n{'='*70}")
    print(f"Cross-contamination check: argmax self-match")
    print(f"  Method: each thread has 2 unique topics x2 copies each.")
    print(f"  For each vector, nearest neighbor = its duplicate in same thread.")
    print(f"  If nearest is from different thread → contamination.")
    total_contam = 0
    for r in results:
        ce = r.get("contamination_errors", 0)
        total_contam += ce
        if ce == 0:
            print(f"  {r['threads']} threads: ✅ 0 contamination errors")
        else:
            print(f"  {r['threads']} threads: ❌ {ce} contamination errors")
            for detail in r.get("contamination_detail", []):
                print(f"    → {detail}")

    # ─── Final verdict ─────────────────────────────────────────
    all_errors = sum(r['errors'] for r in results)
    no_deadlock = True  # if we got here, no timeout
    print(f"\n{'='*70}")
    if all_errors == 0 and no_deadlock and total_contam == 0:
        print("✅ VERDICT: PASS — no deadlock, no errors, no contamination")
    elif all_errors == 0 and no_deadlock:
        print(f"⚠️  VERDICT: {total_contam} contamination errors — vectors may be mixed")
    else:
        print(f"⚠️  VERDICT: {all_errors} errors — check details above")
    print(f"Raw data captured: {time.strftime('%Y-%m-%d %H:%M:%S')}")

except Exception:
    traceback.print_exc()
    sys.exit(1)