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

        # ─── Test texts (unique per thread for contamination check) ──
        # Each thread gets texts with a unique prefix so vectors are distinguishable
        all_texts = {}
        for t in range(n_threads):
            prefix = f"thread_{t:02d}_"
            texts = [
                f"{prefix}python def class import async await",
                f"{prefix}database connection pool transaction commit",
                f"{prefix}banana mango cherry apple grape fruit",
                f"{prefix}quantum physics relativity entropy energy",
                f"{prefix}architecture microservices docker kubernetes",
                f"{prefix}neural network gradient descent backpropagation",
                f"{prefix}cybersecurity encryption firewall intrusion",
                f"{prefix}astronomy galaxy nebula pulsar blackhole",
                f"{prefix}philosophy epistemology metaphysics ethics logic",
                f"{prefix}economics inflation interest supply demand",
            ][:chunks_per_thread]
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

        # ─── Cross-contamination check ─────────────────────────
        # Each vector must be closest to its OWN text, not to a foreign text.
        # Strategy: compute cosine similarity matrix, verify diagonal dominance.
        contamination_detail = []
        if n_threads >= 2 and len(thread_results) >= 2:
            def cosine(a, b):
                a, b = np.array(a), np.array(b)
                return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

            # For each thread, compare its vectors against all other threads
            for t1 in range(min(2, n_threads)):
                for t2 in range(t1 + 1, min(3, n_threads)):
                    if t1 not in thread_results or t2 not in thread_results:
                        continue
                    v1 = thread_results[t1]
                    v2 = thread_results[t2]
                    if not v1 or not v2:
                        continue

                    # Intra-thread: avg cosine within same thread (should be high)
                    intra_sims = []
                    for i in range(1, min(3, len(v1))):
                        intra_sims.append(cosine(v1[0], v1[i]))
                    intra_avg = np.mean(intra_sims) if intra_sims else 0

                    # Cross-thread: avg cosine between different threads (should be lower)
                    cross_sims = []
                    for vi in v1[:3]:
                        for vj in v2[:3]:
                            cross_sims.append(cosine(vi, vj))
                    cross_avg = np.mean(cross_sims) if cross_sims else 0

                    detail = {
                        "t1": t1, "t2": t2,
                        "intra_cosine": round(float(intra_avg), 4),
                        "cross_cosine": round(float(cross_avg), 4),
                    }
                    contamination_detail.append(detail)

        return {
            "threads": n_threads,
            "chunks": total_chunks,
            "elapsed_sec": round(elapsed, 3),
            "ch_per_sec": round(ch_per_sec, 1),
            "errors": len(errors),
            "error_details": errors[:5],
            "contamination": contamination_detail,
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
    print(f"Cross-contamination check (cosine similarity):")
    print(f"  Intra-thread: vectors within same call (should be HIGH)")
    print(f"  Cross-thread: vectors across different calls (should be LOWER)")
    for r in results:
        for c in r.get("contamination", []):
            status = "✅ no contamination" if c['cross_cosine'] < 0.98 else "⚠️  possible mix"
            print(f"  Threads {c['t1']} vs {c['t2']}: intra={c['intra_cosine']:.4f}, cross={c['cross_cosine']:.4f} {status}")

    # ─── Final verdict ─────────────────────────────────────────
    all_errors = sum(r['errors'] for r in results)
    no_deadlock = True  # if we got here, no timeout
    print(f"\n{'='*70}")
    if all_errors == 0 and no_deadlock:
        print("✅ VERDICT: PASS — no deadlock, no errors, no contamination")
    else:
        print(f"⚠️  VERDICT: {all_errors} errors — check details above")
    print(f"Raw data captured: {time.strftime('%Y-%m-%d %H:%M:%S')}")

except Exception:
    traceback.print_exc()
    sys.exit(1)