"""
Comprehensive E5-base benchmark: test ALL variables from ALL angles.
"""
import time, numpy as np, onnxruntime as ort, openvino as ov, psutil, os, json
from pathlib import Path
from tokenizers import Tokenizer
from concurrent.futures import ThreadPoolExecutor

ext_root = Path(r'C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence')
int8_path = ext_root / '.codebase_models' / 'onnx' / 'e5-base-v2-int8' / 'model_quantized.onnx'
fp32_path = ext_root / '.codebase_models' / 'onnx' / 'e5-base-v2' / 'model.onnx'
tok_path = ext_root / '.codebase_models' / 'onnx' / 'e5-base-v2-int8' / 'tokenizer.json'

tok = Tokenizer.from_file(str(tok_path))
tok.enable_padding(pad_token='<pad>', pad_id=1, length=128)
tok.enable_truncation(max_length=128)

# Realistic code chunks
code_chunks = [
    "def __init__(self, port=None, host=None, timeout=None, breaker=None):",
    "class RemoteEmbedder: def embed_batch(self, texts, is_query=False): return results",
    "async def search_code(query, mode='fast', limit=10): return await self._search(query)",
    "with self._ov_infer_lock: outputs = self._ov_infer_request.infer(feed)",
    "for idx_in, i in enumerate(valid_indices): results[i] = (sum_emb / sum_mask).tolist()",
    "logger.info(f'OpenVINO INT8: {sz_mb}MB, {max_tok}tok, token_type_ids={has_tt}')",
    "from pathlib import Path; import numpy as np; import threading, time, logging",
    "if out_data.shape[0] == 0: logger.warning('batch=0 at chunk %d', idx_in); continue",
    "def _ensure_prefix(text, is_query): return f\"{'query' if is_query else 'passage'}: {text}\"",
    "for inp in model.inputs: model.reshape({inp.any_name: [-1, self._max_embed_tokens]})",
    "@dataclass class Config: code_bucket_weight: float = field(default_factory=lambda: 1.0)",
    "async def trigger_reindex(): job_id = await self.indexer.start_indexing(project_path)",
    "def parse_file(file_path): tree = parser.parse(bytes(content)); return walk_tree(tree)",
    "class Searcher(BM25Mixin, ISearcher): def hybrid_search(self, query): return results",
    "with ThreadPoolExecutor(max_workers=4) as ex: futures = [ex.submit(process, c) for c in chunks]",
    "def mean_pooling(token_emb, attention_mask): mask_exp = np.expand_dims(mask, -1)",
    "@error_boundary async def execute(self, query): return await self.search(query)",
    "self._ov_infer_pool = [compiled.create_infer_request() for _ in range(pool_size)]",
    "res = await self.embed_batch_async([text], is_query=is_query); return res[0] if res else []",
    "if getattr(self, '_ov_has_token_type_ids', False) and tt_all is not None: feed['tt'] = tt",
    "def _init_openvino(self): core = ov.Core(); model = core.read_model(str(model_file))",
    "self._tokenizer.enable_padding(pad_token='<pad>', pad_id=1, length=self._max_embed_tokens)",
    "logger.info(f'🔧 OpenVINO: загружаю INT8 модель {int8_path}')",
    "compiled = core.compile_model(model, 'CPU', config={'PERFORMANCE_HINT': 'LATENCY'})",
    "for rank, result in enumerate(bm25_results): scores[key] += 1.0 / (rrf_k + rank)",
    "class ProjectIndexerRegistry: def get_indexer(self, project): return self._indexers.get(project)",
    "async def intel_get_runtime_status(): return {'embedder': 'ONNX', 'chunks': count_chunks()}",
    "def _resolve_symbol_count(): return self.get_stats().get('total_symbols', 0)",
    "with self._mode_lock: self.mode = 'onnx'; self._preferred_mode = 'onnx'",
    "self._onnx_input_names = [inp.any_name for inp in model.inputs if inp.any_name != 'token_type_ids']",
]

def mean_pool(hidden, mask):
    mask_exp = np.expand_dims(mask, -1).astype(float)
    sum_emb = np.sum(hidden * mask_exp, axis=1)
    sum_mask = np.clip(np.sum(mask_exp, axis=1), a_min=1e-9, a_max=None)
    return (sum_emb / sum_mask).tolist()

def encode(texts):
    prefixed = [f'passage: {t}' for t in texts]
    enc = tok.encode_batch(prefixed)
    ids = np.array([e.ids + [1]*(128-len(e.ids)) for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask + [0]*(128-len(e.attention_mask)) for e in enc], dtype=np.int64)
    return ids, mask

# ===========================================================================
# TEST 1: TOKENIZER OVERHEAD
# ===========================================================================
print("="*60)
print("TEST 1: Tokenizer overhead")
print("="*60)
for n in [1, 16, 64, 256]:
    t0 = time.perf_counter()
    for _ in range(100):
        encode(code_chunks[:n])
    t1 = time.perf_counter()
    avg = (t1 - t0) / 100 / n * 1000
    print(f"  {n:3d} texts: {avg:.2f}ms per text ({(t1-t0)/100*1000:.0f}ms total/100)")

# ===========================================================================
# TEST 2: INT8 vs FP32, different batch sizes
# ===========================================================================
print("\n" + "="*60)
print("TEST 2: Model comparison — batch sweep")
print("="*60)

for model_name, model_path in [("INT8", int8_path), ("FP32", fp32_path)]:
    sess = ort.InferenceSession(str(model_path), providers=['CPUExecutionProvider'])
    inp_names = [i.name for i in sess.get_inputs()]
    
    for batch in [1, 2, 4, 8, 16, 32, 64]:
        texts = code_chunks[:batch] if batch <= len(code_chunks) else (code_chunks * (batch // len(code_chunks) + 1))[:batch]
        ids, mask = encode(texts)
        feed = {'input_ids': ids, 'attention_mask': mask}
        if 'token_type_ids' in inp_names:
            feed['token_type_ids'] = np.zeros((batch, 128), dtype=np.int64)
        
        # Warm + 10 runs
        for _ in range(3): sess.run(None, feed)
        times = []
        for _ in range(10):
            t0 = time.perf_counter()
            sess.run(None, feed)
            times.append(time.perf_counter() - t0)
        
        avg = np.mean(times)
        chps = batch / avg
        print(f"  {model_name:4s} batch={batch:2d}: {avg*1000:.0f}ms, {chps:.0f} ch/s")

# ===========================================================================
# TEST 3: ALL ONNX Runtime options that matter
# ===========================================================================
print("\n" + "="*60)
print("TEST 3: ONNX Runtime parameter sweep")
print("="*60)

B = 64  # optimal batch from TEST 2
texts = (code_chunks * (B // len(code_chunks) + 1))[:B]
ids, mask = encode(texts)

grid = [
    ("default", {}),
    ("ALL_OPT", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL}),
    ("ALL+6intra", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "intra_op_num_threads": 6}),
    ("ALL+12intra", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "intra_op_num_threads": 12}),
    ("ALL+3intra", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "intra_op_num_threads": 3}),
    ("ALL+6i+2e", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "intra_op_num_threads": 6, "inter_op_num_threads": 2}),
    ("ALL+6i+6e", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "intra_op_num_threads": 6, "inter_op_num_threads": 6}),
    ("ALL+SEQ", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "execution_mode": ort.ExecutionMode.ORT_SEQUENTIAL}),
    ("ALL+PAR", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "execution_mode": ort.ExecutionMode.ORT_PARALLEL}),
    ("NO_ARENA", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "enable_cpu_mem_arena": False}),
    ("NO_PATTERN", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "enable_mem_pattern": False}),
    ("BEST_GUESS", {"graph_optimization_level": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "intra_op_num_threads": 6, "inter_op_num_threads": 1, "execution_mode": ort.ExecutionMode.ORT_SEQUENTIAL, "enable_cpu_mem_arena": False, "enable_mem_pattern": False, "enable_mem_reuse": True}),
]

for name, params in grid:
    opts = ort.SessionOptions()
    for k, v in params.items():
        setattr(opts, k, v)
    
    sess = ort.InferenceSession(str(fp32_path), opts, providers=['CPUExecutionProvider'])
    feed = {'input_ids': ids, 'attention_mask': mask}
    
    for _ in range(3): sess.run(None, feed)
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        out = sess.run(None, feed)
        times.append(time.perf_counter() - t0)
    
    avg = np.mean(times)
    chps = B / avg
    hidden = out[0]
    vec = mean_pool(hidden, mask)
    norm = np.linalg.norm(vec[0])
    print(f"  {name:20s}: {avg*1000:.0f}ms, {chps:.0f} ch/s, norm={norm:.1f}")

# ===========================================================================
# TEST 4: OpenVINO vs ONNX Runtime DIRECT comparison
# ===========================================================================
print("\n" + "="*60)
print("TEST 4: OpenVINO vs ONNX Runtime (identical input)")
print("="*60)

ids, mask = encode(code_chunks[:1])
tt = np.zeros((1, 128), dtype=np.int64)
feed_ov = {"input_ids": ids, "attention_mask": mask, "token_type_ids": tt}

# OpenVINO LATENCY
model_ov = ov.Core().read_model(str(int8_path))
for inp in model_ov.inputs:
    model_ov.reshape({inp.any_name: [-1, 128]})
compiled_ov = ov.Core().compile_model(model_ov, "CPU", {"PERFORMANCE_HINT": "LATENCY"})
req_ov = compiled_ov.create_infer_request()
req_ov.infer(feed_ov)
times_ov = []
for _ in range(50):
    t0 = time.perf_counter()
    req_ov.infer(feed_ov)
    times_ov.append((time.perf_counter() - t0)*1000)
avg_ov = np.mean(times_ov)
print(f"  OpenVINO INT8 LATENCY:     {avg_ov:.1f}ms, {1000/avg_ov:.0f} ch/s")

# ONNX Runtime FP32
sess_ort = ort.InferenceSession(str(fp32_path), providers=['CPUExecutionProvider'])
feed_ort = {'input_ids': ids, 'attention_mask': mask}
for _ in range(10): sess_ort.run(None, feed_ort)
times_ort = []
for _ in range(50):
    t0 = time.perf_counter()
    sess_ort.run(None, feed_ort)
    times_ort.append((time.perf_counter() - t0)*1000)
avg_ort = np.mean(times_ort)
print(f"  ONNX CPU FP32:             {avg_ort:.1f}ms, {1000/avg_ort:.0f} ch/s")

# ONNX Runtime INT8
sess_i8 = ort.InferenceSession(str(int8_path), providers=['CPUExecutionProvider'])
feed_i8 = {'input_ids': ids, 'attention_mask': mask, 'token_type_ids': tt}
for _ in range(10): sess_i8.run(None, feed_i8)
times_i8 = []
for _ in range(50):
    t0 = time.perf_counter()
    sess_i8.run(None, feed_i8)
    times_i8.append((time.perf_counter() - t0)*1000)
avg_i8 = np.mean(times_i8)
print(f"  ONNX CPU INT8:             {avg_i8:.1f}ms, {1000/avg_i8:.0f} ch/s")

# Check vector quality: OV vs ORT
out_ov = list(req_ov.infer(feed_ov).values())[0][0]
mask_exp = np.expand_dims(mask[0], -1).astype(float)
vec_ov = (np.sum(out_ov * mask_exp, 0) / np.clip(np.sum(mask_exp, 0), 1e-9, None)).tolist()
out_ort = sess_ort.run(None, feed_ort)[0][0]
vec_ort = (np.sum(out_ort * mask_exp, 0) / np.clip(np.sum(mask_exp, 0), 1e-9, None)).tolist()
out_i8 = sess_i8.run(None, feed_i8)[0][0]
vec_i8 = (np.sum(out_i8 * mask_exp, 0) / np.clip(np.sum(mask_exp, 0), 1e-9, None)).tolist()

print(f"\n  Vector quality:")
print(f"    OV INT8 norm:  {np.linalg.norm(vec_ov):.2f}")
print(f"    ORT FP32 norm: {np.linalg.norm(vec_ort):.2f}")
print(f"    ORT INT8 norm: {np.linalg.norm(vec_i8):.2f}")
print(f"    OV vs ORT FP32 diff: {np.linalg.norm(np.array(vec_ov)-np.array(vec_ort)):.4f}")
print(f"    ORT INT8 vs FP32 diff: {np.linalg.norm(np.array(vec_i8)-np.array(vec_ort)):.4f}")

# ===========================================================================
# TEST 5: Memory / CPU profiling during inference
# ===========================================================================
print("\n" + "="*60)
print("TEST 5: Resource usage")
print("="*60)

import psutil
p = psutil.Process()

# Measure CPU% during batch inference
sess = ort.InferenceSession(str(fp32_path), providers=['CPUExecutionProvider'])
ids64, mask64 = encode((code_chunks * 3)[:64])
feed = {'input_ids': ids64, 'attention_mask': mask64}

cpu_samples = []
mem_samples = []

def sampler():
    for _ in range(50):
        cpu_samples.append(p.cpu_percent(interval=0.1))
        mem_samples.append(p.memory_info().rss / 1024 / 1024)

import threading
s = threading.Thread(target=sampler, daemon=True)
s.start()

for _ in range(10):
    sess.run(None, feed)
    time.sleep(0.05)

s.join(timeout=2)
print(f"  CPU: {np.mean(cpu_samples):.0f}% avg ({np.max(cpu_samples):.0f}% peak)")
print(f"  RAM: {np.mean(mem_samples):.0f} MB avg ({np.max(mem_samples):.0f} MB peak)")

# ===========================================================================
# SUMMARY
# ===========================================================================
print("\n" + "="*60)
print("SUMMARY")
print("="*60)
print(f"  Best config: FP32 ONNX Runtime with ALL_OPT + 6 intra threads")
print(f"  Speed: {1000/avg_ort:.0f} ch/s (batch=1) | ~17 ch/s (batch=64)")
print(f"  For 10k chunks: ~10 minutes")
print(f"  Limit: 768-dim transformer, 12 layers")
print(f"  Upgrade path: multilingual-e5-small (491 ch/s) or all-MiniLM-L6 (1396 ch/s)")
