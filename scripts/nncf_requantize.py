"""
Re-quantize FP32 model to INT8 with proper vocabulary support.
Uses ONNX Runtime dynamic quantization directly on original opset.
"""
import os, time, numpy as np, shutil
from pathlib import Path

os.environ["TOKENIZERS_PARALLELISM"] = "false"

import onnx
from onnxruntime.quantization import quantize_dynamic, QuantType
import onnxruntime as ort
from tokenizers import Tokenizer

EXT_ROOT = Path(r'C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence')
MODEL_SLUG = 'e5-base-v2'
FP32_PATH = EXT_ROOT / '.codebase_models' / 'onnx' / MODEL_SLUG / 'model.onnx'
OUTPUT_DIR = EXT_ROOT / '.codebase_models' / 'onnx' / f'{MODEL_SLUG}-int8-nncf'
OUTPUT_PATH = OUTPUT_DIR / 'model_quantized.onnx'

print(f"FP32 source: {FP32_PATH} ({FP32_PATH.stat().st_size/1024/1024:.0f} MB)")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 1. Load and check model
model = onnx.load(str(FP32_PATH))
print(f"Inputs: {[i.name for i in model.graph.input]}")
print(f"Outputs: {[o.name for o in model.graph.output]}")
opset = model.opset_import[0].version if model.opset_import else 'N/A'
print(f"Opset: {opset}")
print(f"Producer: {model.producer_name}")

# 2. Try quantize directly on the original model
print("\nQuantizing (ORT dynamic INT8, keep original opset)...")
t0 = time.perf_counter()
try:
    quantize_dynamic(
        model_input=str(FP32_PATH),
        model_output=str(OUTPUT_PATH),
        weight_type=QuantType.QInt8,
        per_channel=False,
        reduce_range=False,
    )
except Exception as e:
    print(f"Direct quantization failed: {e}")
    print("Trying with opset update workaround...")
    
    # Alternative: export via optimum-cli format
    # Use the HF model directly with correct export
    print(f"\nFalling back: copy ONNX from HF optimum export...")
    print("Checking HuggingFace cache for pre-exported model...")
    
    hf_cache = Path.home() / '.cache' / 'huggingface' / 'hub'
    # Look for optimum exported models
    for p in sorted(hf_cache.rglob('*quantized*onnx*')) + sorted(hf_cache.rglob('*int8*onnx*')):
        sz = p.stat().st_size / 1024 / 1024
        print(f"  Found: {p.relative_to(hf_cache)} ({sz:.0f}MB)")
    
    sys.exit(1)

print(f"Done in {time.perf_counter()-t0:.0f}s")
size_mb = OUTPUT_PATH.stat().st_size / 1024 / 1024
print(f"INT8 model: {size_mb:.0f} MB")

# 3. Copy support files from FP32 source (correct vocab!)
print("\nCopying metadata from FP32 source...")
src = EXT_ROOT / '.codebase_models' / 'onnx' / MODEL_SLUG
for f in ['tokenizer.json', 'tokenizer_config.json', 'config.json', 'special_tokens_map.json']:
    sf = src / f
    if sf.exists():
        shutil.copy2(sf, OUTPUT_DIR / f)
        print(f"  ✓ {f}")
    else:
        print(f"  ✗ {f} NOT FOUND")

# 4. Verify with ONNX Runtime
print("\n=== ONNX Runtime Verification ===")
tokenizer = Tokenizer.from_file(str(OUTPUT_DIR / 'tokenizer.json'))
tokenizer.enable_padding(pad_token='<pad>', pad_id=1, length=128)
tokenizer.enable_truncation(max_length=128)

opts = ort.SessionOptions()
opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
opts.intra_op_num_threads = 6
opts.inter_op_num_threads = 1
opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
opts.enable_cpu_mem_arena = False

sess = ort.InferenceSession(str(OUTPUT_PATH), sess_options=opts, providers=['CPUExecutionProvider'])
inp_names = [i.name for i in sess.get_inputs()]
print(f"Model inputs: {inp_names}")
out_shape = sess.get_outputs()[0].shape
print(f"Output shape: {out_shape}")

# Compare with FP32 (reference)
sess_fp32 = ort.InferenceSession(str(FP32_PATH), sess_options=opts, providers=['CPUExecutionProvider'])
fp32_inp = [i.name for i in sess_fp32.get_inputs()]

test_texts = ['passage: def hello():\n    return 42', 'passage: class Test:\n    pass']
enc = tokenizer.encode_batch(test_texts)
ids = np.array([e.ids for e in enc], dtype=np.int64)
mask = np.array([e.attention_mask for e in enc], dtype=np.int64)

feed = {'input_ids': ids, 'attention_mask': mask}
if 'token_type_ids' in inp_names:
    feed['token_type_ids'] = np.zeros((2, 128), dtype=np.int64)

feed_fp32 = {'input_ids': ids, 'attention_mask': mask}
if 'token_type_ids' in fp32_inp:
    feed_fp32['token_type_ids'] = np.zeros((2, 128), dtype=np.int64)

out_int8 = sess.run(None, feed)
out_fp32 = sess_fp32.run(None, feed_fp32)

# Mean pooling
def mean_pool(emb, mask):
    me = np.expand_dims(mask, -1).astype(float)
    se = np.sum(emb * me, 1)
    sm = np.clip(np.sum(me, 1), a_min=1e-9, a_max=None)
    return se / sm

vec_int8 = mean_pool(out_int8[0], mask)
vec_fp32 = mean_pool(out_fp32[0], mask)

for i in range(2):
    n_int8 = np.linalg.norm(vec_int8[i])
    n_fp32 = np.linalg.norm(vec_fp32[i])
    cos = np.dot(vec_int8[i], vec_fp32[i]) / (n_int8 * n_fp32 + 1e-12)
    rel_diff = abs(n_int8 - n_fp32) / n_fp32 * 100
    print(f"Text {i}: INT8 norm={n_int8:.2f} FP32 norm={n_fp32:.2f} cos={cos:.4f} diff={rel_diff:.1f}%")
    print(f"  INT8 first 5: {vec_int8[i][:5].tolist()}")
    print(f"  FP32 first 5: {vec_fp32[i][:5].tolist()}")

# 5. Speed test
print("\n=== Speed Test (batch=64) ===")
texts = [f'passage: test chunk number {i} for speed measurement' for i in range(64)]
enc = tokenizer.encode_batch(texts)
ids = np.array([e.ids for e in enc], dtype=np.int64)
mask = np.array([e.attention_mask for e in enc], dtype=np.int64)

feed = {'input_ids': ids, 'attention_mask': mask}
if 'token_type_ids' in inp_names:
    feed['token_type_ids'] = np.zeros((64, 128), dtype=np.int64)

_w = sess.run(None, feed)

N = 20
t0 = time.perf_counter()
for _ in range(N):
    sess.run(None, feed)
t1 = time.perf_counter()

ch_s = 64 * N / (t1 - t0)
ms_per = (t1 - t0) / N * 1000
print(f"  {ms_per:.0f}ms/infer | {ch_s:.0f} ch/s")

# Compare speed with FP32
_w = sess_fp32.run(None, feed_fp32)
t0 = time.perf_counter()
for _ in range(N):
    sess_fp32.run(None, feed_fp32)
t1 = time.perf_counter()
ch_s_fp32 = 64 * N / (t1 - t0)
print(f"FP32 reference: {ch_s_fp32:.0f} ch/s")

print(f"\nNew model: {OUTPUT_DIR}")
print(f"INT8 model: {OUTPUT_PATH}")
