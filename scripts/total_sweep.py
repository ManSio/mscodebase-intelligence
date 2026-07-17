"""
Total parameter sweep: find what gave 350 ch/s.
Tests ALL combinations systematically.
"""
import time, numpy as np, onnxruntime as ort, openvino as ov
from pathlib import Path
from tokenizers import Tokenizer

ext_root = Path(r'C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence')
int8_path = ext_root / '.codebase_models' / 'onnx' / 'e5-base-v2-int8' / 'model_quantized.onnx'
fp32_path = ext_root / '.codebase_models' / 'onnx' / 'e5-base-v2' / 'model.onnx'
tok_path = ext_root / '.codebase_models' / 'onnx' / 'e5-base-v2-int8' / 'tokenizer.json'
tok = Tokenizer.from_file(str(tok_path))
tok.enable_padding(pad_token='<pad>', pad_id=1, length=128)
tok.enable_truncation(max_length=128)

code_chunks = [f"code chunk {i}: def func_{i}(param): return param * 2" for i in range(64)]
prefixed = [f'passage: {t}' for t in code_chunks]
enc = tok.encode_batch(prefixed)
ids = np.array([e.ids + [1]*(128-len(e.ids)) for e in enc], dtype=np.int64)
mask = np.array([e.attention_mask + [0]*(128-len(e.attention_mask)) for e in enc], dtype=np.int64)
tt = np.zeros((64, 128), dtype=np.int64)
tt_auto = np.array([getattr(e, 'type_ids', None) or [0]*128 for e in enc], dtype=np.int64)

def mean_pool(hidden, attn_mask):
    me = np.expand_dims(attn_mask, -1).astype(float)
    se = np.sum(hidden * me, axis=1)
    sm = np.clip(np.sum(me, axis=1), a_min=1e-9, a_max=None)
    return (se / sm).tolist()

results = []

# ═══════════════════════════════════════════════════
# 1. ONNX Runtime — FP32 — all combos
# ═══════════════════════════════════════════════════
print("=== ONNX FP32 ===")
for opt in ['BASIC', 'EXTENDED', 'ALL']:
    for mode in ['SEQUENTIAL', 'PARALLEL']:
        for intra in [1, 6, 12]:
            for inter in [1, 2]:
                for batch in [1, 16, 64]:
                    b_ids = ids[:batch] if batch <= 64 else ids
                    b_mask = mask[:batch] if batch <= 64 else mask
                    
                    opts = ort.SessionOptions()
                    setattr(opts, 'graph_optimization_level', getattr(ort.GraphOptimizationLevel, f'ORT_ENABLE_{opt}'))
                    setattr(opts, 'intra_op_num_threads', intra)
                    setattr(opts, 'inter_op_num_threads', inter)
                    setattr(opts, 'execution_mode', getattr(ort.ExecutionMode, f'ORT_{mode}'))
                    
                    try:
                        sess = ort.InferenceSession(str(fp32_path), opts, providers=['CPUExecutionProvider'])
                        feed = {'input_ids': b_ids, 'attention_mask': b_mask}
                        for _ in range(2): sess.run(None, feed)
                        t0 = time.perf_counter()
                        out = sess.run(None, feed)
                        dt = time.perf_counter() - t0
                        vecs = mean_pool(out[0], b_mask)
                        norms = [np.linalg.norm(v) for v in vecs]
                        z = sum(1 for n in norms if n < 0.01)
                        print(f"FP32 {opt}+{mode}+i{intra}+e{inter} b{batch:2d}: {dt*1000:6.0f}ms {batch/dt:5.0f}ch/s zeros={z}")
                    except Exception as e:
                        print(f"FP32 {opt}+{mode}+i{intra}+e{inter} b{batch:2d}: FAIL {str(e)[:40]}")
                    time.sleep(0.05)

# ═══════════════════════════════════════════════════
# 2. ONNX Runtime — INT8 — tt modes
# ═══════════════════════════════════════════════════
print("\n=== ONNX INT8 ===")
for opt in ['BASIC', 'ALL']:
    for intra in [6, 12]:
        for tt_mode in ['zeros', 'auto']:
            for batch in [1, 64]:
                b_ids = ids[:batch]; b_mask = mask[:batch]
                opts = ort.SessionOptions()
                setattr(opts, 'graph_optimization_level', getattr(ort.GraphOptimizationLevel, f'ORT_ENABLE_{opt}'))
                setattr(opts, 'intra_op_num_threads', intra)
                
                try:
                    sess = ort.InferenceSession(str(int8_path), opts, providers=['CPUExecutionProvider'])
                    feed = {'input_ids': b_ids, 'attention_mask': b_mask}
                    if tt_mode == 'zeros': feed['token_type_ids'] = np.zeros((batch, 128), dtype=np.int64)
                    else: feed['token_type_ids'] = tt_auto[:batch]
                    for _ in range(2): sess.run(None, feed)
                    t0 = time.perf_counter()
                    out = sess.run(None, feed)
                    dt = time.perf_counter() - t0
                    vecs = mean_pool(out[0], b_mask)
                    norms = [np.linalg.norm(v) for v in vecs]
                    z = sum(1 for n in norms if n < 0.01)
                    print(f"INT8 {opt}+i{intra}+tt{tt_mode} b{batch:2d}: {dt*1000:6.0f}ms {batch/dt:5.0f}ch/s zeros={z}")
                except Exception as e:
                    print(f"INT8 {opt}+i{intra}+tt{tt_mode} b{batch:2d}: FAIL {str(e)[:40]}")
                time.sleep(0.05)

# ═══════════════════════════════════════════════════
# 3. OpenVINO — INT8 — all hint modes
# ═══════════════════════════════════════════════════
print("\n=== OpenVINO INT8 ===")
core = ov.Core()
for hint in ['LATENCY', 'THROUGHPUT']:
    for streams in ['1', '2', '4', 'auto']:
        for tt_mode in [True, False]:
            try:
                model = core.read_model(str(int8_path))
                for inp in model.inputs: model.reshape({inp.any_name: [-1, 128]})
                cfg = {'PERFORMANCE_HINT': hint, 'INFERENCE_NUM_THREADS': '0'}
                if streams != 'auto': cfg['NUM_STREAMS'] = streams
                
                compiled = core.compile_model(model, "CPU", cfg)
                req = compiled.create_infer_request()
                
                feed = {'input_ids': ids, 'attention_mask': mask, 'token_type_ids': tt} if tt_mode else {'input_ids': ids, 'attention_mask': mask}
                req.infer(feed)
                t0 = time.perf_counter()
                out = req.infer(feed)
                dt = time.perf_counter() - t0
                
                out_t = list(out.values())[0]
                zero = out_t.shape[0] == 0
                norm = np.linalg.norm(out_t[0]) if not zero else 0
                print(f"OV {hint}+s{streams}+tt{tt_mode}: {dt*1000:6.0f}ms {64/dt:5.0f}ch/s batch0={zero} norm={norm:.1f}")
            except Exception as e:
                print(f"OV {hint}+s{streams}+tt{tt_mode}: FAIL {str(e)[:40]}")
            time.sleep(0.05)

# ═══════════════════════════════════════════════════
# 4. e5-small ONNX (384-dim) — как референс
# ═══════════════════════════════════════════════════
print("\n=== e5-small ONNX ===")
try:
    from optimum.onnxruntime import ORTModelForFeatureExtraction
    from transformers import AutoTokenizer
    ort_small = ORTModelForFeatureExtraction.from_pretrained('intfloat/multilingual-e5-small', export=True)
    tok_small = AutoTokenizer.from_pretrained('intfloat/multilingual-e5-small')
    
    for batch in [1, 64]:
        txts = [f'passage: {t}' for t in code_chunks[:batch]]
        enc_s = tok_small(txts, padding=True, truncation=True, max_length=128, return_tensors='np')
        
        for _ in range(2): ort_small(input_ids=enc_s['input_ids'], attention_mask=enc_s['attention_mask'])
        t0 = time.perf_counter()
        out_s = ort_small(input_ids=enc_s['input_ids'], attention_mask=enc_s['attention_mask'])
        dt = time.perf_counter() - t0
        
        vecs = mean_pool(out_s.last_hidden_state.numpy(), enc_s['attention_mask'].numpy())
        norms = [np.linalg.norm(v) for v in vecs]
        print(f"E5-small b{batch:2d}: {dt*1000:6.0f}ms {batch/dt:5.0f}ch/s norm={norms[0]:.1f}")
except Exception as e:
    print(f"E5-small: FAIL {e}")

print("\n=== DONE ===")
