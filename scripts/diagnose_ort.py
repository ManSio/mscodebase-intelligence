"""
Диагностика: какой провайдер ONNX реально используется и сколько CPU.
"""
import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import os, time, numpy as np
from pathlib import Path
import onnxruntime as ort

EXT_DIR = Path(os.environ.get("EXT_DIR", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
MODEL_FILE = EXT_DIR / ".codebase_models" / "onnx" / "multilingual-e5-small-int8" / "model_quantized.onnx"

print("=== ONNX Runtime диагностика ===")
print(f"Версия ORT: {ort.__version__}")
print(f"Доступные провайдеры: {ort.get_available_providers()}")

# Проверяем все возможные провайдеры
for p in ort.get_available_providers():
    try:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 8
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        sess = ort.InferenceSession(str(MODEL_FILE), sess_options=opts, providers=[p])
        # Тестовый запуск
        inp = {sess.get_inputs()[0].name: np.ones((4,128), dtype=np.int64)}
        if len(sess.get_inputs()) > 1:
            inp[sess.get_inputs()[1].name] = np.ones((4,128), dtype=np.int64)
        if len(sess.get_inputs()) > 2:
            inp[sess.get_inputs()[2].name] = np.zeros((4,128), dtype=np.int64)
        
        t0 = time.perf_counter()
        for _ in range(10):
            sess.run(None, inp)
        dt = (time.perf_counter() - t0) / 10
        print(f"\n✅ {p}: {dt*1000:.1f}ms на батч (4x128)")
    except Exception as e:
        print(f"\n❌ {p}: {e}")

print("\n=== Текущий production код ===")
print("ONNX_PROVIDERS env:", repr(os.getenv("ONNX_PROVIDERS", "")))
print("ONNX_INTRA_THREADS env:", repr(os.getenv("ONNX_INTRA_THREADS", "")))
