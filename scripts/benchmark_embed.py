"""
🧪 Эксперимент: замер скорости эмбеддинга по фазам.
Сравнение с эталоном из EXPERIMENTS_LOG.md (52 ch/s, batch=4).
"""
import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import os
import time
import json
from pathlib import Path

# Путь к расширению
EXT_DIR = Path(os.environ.get("EXT_DIR", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
MODEL_DIR = EXT_DIR / ".codebase_models" / "onnx" / "multilingual-e5-small-int8"
MODEL_FILE = MODEL_DIR / "model_quantized.onnx"

print("=" * 60)
print("🧪 BENCHMARK: multilingual-e5-small-int8")
print("=" * 60)
print(f"Model: {MODEL_FILE}")
print(f"Exists: {MODEL_FILE.exists()}")
print()

# 1. Определяем доступные провайдеры ONNX
import onnxruntime as ort
avail = ort.get_available_providers()
print(f"📋 Доступные провайдеры ONNX Runtime: {avail}")

# 2. Создаём сессию с теми же параметрами, что в production
opts = ort.SessionOptions()
opts.enable_cpu_mem_arena = False
opts.enable_mem_pattern = False
opts.enable_mem_reuse = True
opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
opts.intra_op_num_threads = int(os.getenv("ONNX_INTRA_THREADS", "8"))
opts.inter_op_num_threads = int(os.getenv("ONNX_INTER_THREADS", "1"))
opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

# Провайдеры — как в production (CPU + DML если доступен)
providers = ["CPUExecutionProvider"]
if "DmlExecutionProvider" in avail:
    providers.insert(0, "DmlExecutionProvider")

print(f"📋 Используемые провайдеры: {providers}")
print(f"📋 intra_op_num_threads={opts.intra_op_num_threads}")
print(f"📋 execution_mode={opts.execution_mode}")
print()

session = ort.InferenceSession(str(MODEL_FILE), sess_options=opts, providers=providers)
input_names = [inp.name for inp in session.get_inputs()]
print(f"📋 Входы модели: {input_names}")

# 3. Токенизатор (как в production)
from tokenizers import Tokenizer
tokenizer_path = MODEL_DIR / "tokenizer.json"
tokenizer = Tokenizer.from_file(str(tokenizer_path))
tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=128)
tokenizer.enable_truncation(max_length=128)

# 4. Тестовые тексты — реальные чанки из проекта
test_texts = [
    "// Scope: function | core.config | from src.config.settings import get_config\nclass ConfigManager:\n    def __init__(self):\n        self.config = get_config()",
    "// Scope: function | core.indexer | def index_project(self, project_path):\n    \"\"\"Full project indexing.\"\"\"\n    for root, dirs, files in os.walk(project_path):",
    "// Scope: class | providers.embedder | class RemoteEmbedder(IEmbedder):\n    def embed_batch(self, texts, is_query=False):\n        \"\"\"Batch embedding.\"\"\"",
    "// Scope: function | server.mcp | async def handle_request(self, request):\n    \"\"\"Handle incoming MCP request.\"\"\"\n    result = await self.dispatch(request)",
]

# 5. Бенчмарк по фазам
BATCH_SIZE = 4
WARMUP = 5
ITERATIONS = 50

def _ensure_prefix(text: str, is_query: bool) -> str:
    for prefix in ("query: ", "passage: "):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return f"{'query' if is_query else 'passage'}: {text}"

print("\n" + "=" * 60)
print("🏗️  БЕНЧМАРК: batch=4, iter=50")
print("=" * 60)

times_encode = []
times_infer = []
times_total = []

for i in range(WARMUP + ITERATIONS):
    # Prefix
    t0 = time.perf_counter()
    prefixed = [_ensure_prefix(t, False) for t in test_texts]
    
    # Tokenize
    t1 = time.perf_counter()
    enc = tokenizer.encode_batch(prefixed, add_special_tokens=True)
    t2 = time.perf_counter()
    
    # Prepare inputs
    import numpy as np
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    inputs = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in input_names:
        tt = np.array([getattr(e, "type_ids", None) or [0]*len(e.ids) for e in enc], dtype=np.int64)
        inputs["token_type_ids"] = tt
    
    # Infer
    t3 = time.perf_counter()
    outputs = session.run(None, inputs)
    t4 = time.perf_counter()
    
    # Post-process (mean pooling)
    token_emb = outputs[0]
    mask_exp = np.expand_dims(mask, -1).astype(float)
    sum_emb = np.sum(token_emb * mask_exp, 1)
    sum_mask = np.clip(np.sum(mask_exp, 1), a_min=1e-9, a_max=None)
    result = (sum_emb / sum_mask).tolist()
    t5 = time.perf_counter()
    
    if i >= WARMUP:
        times_encode.append((t2 - t1) * 1000)  # ms
        times_infer.append((t4 - t3) * 1000)   # ms
        times_total.append((t5 - t0) * 1000)   # ms

# Статистика
def stats(arr):
    return {
        "min_ms": round(min(arr), 2),
        "max_ms": round(max(arr), 2),
        "avg_ms": round(sum(arr) / len(arr), 2),
        "ch/s": round(1000 / (sum(arr) / len(arr)) * BATCH_SIZE, 1),
    }

encode_s = stats(times_encode)
infer_s = stats(times_infer)
total_s = stats(times_total)

print(f"\n{'Фаза':<25} {'min(ms)':<10} {'avg(ms)':<10} {'max(ms)':<10} {'ch/s':<10}")
print("-" * 65)
print(f"{'encode_batch (токенизация)':<25} {encode_s['min_ms']:<10} {encode_s['avg_ms']:<10} {encode_s['max_ms']:<10} {encode_s['ch/s']:<10}")
print(f"{'session.run (инференс)':<25} {infer_s['min_ms']:<10} {infer_s['avg_ms']:<10} {infer_s['max_ms']:<10} {infer_s['ch/s']:<10}")
print(f"{'total (полный цикл)':<25} {total_s['min_ms']:<10} {total_s['avg_ms']:<10} {total_s['max_ms']:<10} {total_s['ch/s']:<10}")

# Сравнение с эталоном
print("\n" + "=" * 60)
print("📊 СРАВНЕНИЕ С ЭТАЛОНОМ")
print("=" * 60)
target = 52  # ch/s из EXPERIMENTS_LOG.md
actual = total_s["ch/s"]
print(f"Эталон (EXPERIMENTS_LOG.md): {target} ch/s")
print(f"Текущий замер:               {actual} ch/s")
print(f"Отклонение:                  {round((actual - target) / target * 100, 1)}%")

if actual < target * 0.8:
    print("\n⚠️  Скорость ниже эталона >20%. Возможные причины:")
    if encode_s["avg_ms"] > 5:
        print(f"  - encode_batch медленный: {encode_s['avg_ms']}ms")
    if infer_s["avg_ms"] > 20:
        print(f"  - session.run медленный: {infer_s['avg_ms']}ms")
    if "DmlExecutionProvider" in providers and "DmlExecutionProvider" in avail:
        print("  - DirectML активен (может переключать на GPU)")
    print("  - Проверь ONNX_INTRA_THREADS, частоту процессора, троттлинг")
