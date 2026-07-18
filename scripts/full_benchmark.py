"""
Полный эксперимент: все комбинации ONNX Runtime конфигов.
Замеряет скорость embed и определяет точную причину тормозов.
Результат записывается в EXPERIMENTS_LOG.md
"""
import sys, os, time, json, numpy as np
from pathlib import Path
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

EXT_DIR = Path(os.environ.get("EXT_DIR", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
MODEL_FILE = EXT_DIR / ".codebase_models" / "onnx" / "multilingual-e5-small-int8" / "model_quantized.onnx"
TOKENIZER_FILE = MODEL_FILE.parent / "tokenizer.json"

print("=" * 70)
print("🧪 ПОЛНЫЙ ЭКСПЕРИМЕНТ: ONNX Runtime конфиги")
print("=" * 70)

# 1. Проверка модели
print(f"\n📦 Модель: {MODEL_FILE}")
print(f"   Существует: {MODEL_FILE.exists()}")
print(f"   Размер: {MODEL_FILE.stat().st_size / 1e6:.1f} MB")
print(f"   Токенизатор: {TOKENIZER_FILE.exists()}")

# 2. Проверка файлов расширения
print("\n📂 Файлы расширения (core/indexing/):")
for f in ["index_parser.py", "index_project_runner.py", "indexer.py", "symbol_index.py"]:
    p = EXT_DIR / "src" / "core" / "indexing" / f
    print(f"   {f}: {'✅' if p.exists() else '❌'} {p.stat().st_size/1e3:.1f}KB" if p.exists() else f"   {f}: ❌")

print("\n📂 Файлы расширения (providers/embedder/):")
for f in ["remote_embedder.py"]:
    p = EXT_DIR / "src" / "providers" / "embedder" / f
    print(f"   {f}: {'✅' if p.exists() else '❌'} {p.stat().st_size/1e3:.1f}KB" if p.exists() else f"   {f}: ❌")

print("\n📂 Файлы расширения (intelligence/):")
for f in ["layer.py"]:
    p = EXT_DIR / "src" / "core" / "intelligence" / f
    print(f"   {f}: {'✅' if p.exists() else '❌'} {p.stat().st_size/1e3:.1f}KB" if p.exists() else f"   {f}: ❌")

# 3. Проверка версий
import onnxruntime as ort
print(f"\n📋 ONNX Runtime: {ort.__version__}")
print(f"📋 Доступные провайдеры: {ort.get_available_providers()}")

from tokenizers import Tokenizer
tokenizer = Tokenizer.from_file(str(TOKENIZER_FILE))
tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=128)
tokenizer.enable_truncation(max_length=128)

# 4. Тестовые тексты (реальные чанки)
test_texts = [
    "passage: // Scope: function | core.config | from src.config.settings import get_config\nclass ConfigManager:\n    def __init__(self):\n        self.config = get_config()",
    "passage: // Scope: function | core.indexer | def index_project(self, project_path):\n    \"\"\"Full project indexing.\"\"\"\n    for root, dirs, files in os.walk(project_path):",
    "passage: // Scope: class | providers.embedder | class RemoteEmbedder(IEmbedder):\n    def embed_batch(self, texts, is_query=False):\n        \"\"\"Batch embedding.\"\"\"",
    "passage: // Scope: function | server.mcp | async def handle_request(self, request):\n    \"\"\"Handle incoming MCP request.\"\"\"\n    result = await self.dispatch(request)",
]

BATCH_SIZE = 4
WARMUP = 5
ITERATIONS = 30

def run_benchmark(providers, opts_mods: dict, label: str) -> dict:
    """Замер для конкретной конфигурации."""
    opts = ort.SessionOptions()
    opts.enable_cpu_mem_arena = opts_mods.get("arena", False)
    opts.enable_mem_pattern = opts_mods.get("mem_pattern", True)
    opts.enable_mem_reuse = True
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.intra_op_num_threads = opts_mods.get("intra", 8)
    opts.inter_op_num_threads = opts_mods.get("inter", 1)
    opts.execution_mode = ort.ExecutionMode.ORT_PARALLEL if opts_mods.get("parallel") else ort.ExecutionMode.ORT_SEQUENTIAL

    try:
        sess = ort.InferenceSession(str(MODEL_FILE), sess_options=opts, providers=providers)
    except Exception as e:
        return {"label": label, "error": str(e), "ch_s": 0, "avg_ms": 0}
    
    # Warmup
    inp = {sess.get_inputs()[0].name: np.ones((BATCH_SIZE, 128), dtype=np.int64)}
    if len(sess.get_inputs()) > 1:
        inp[sess.get_inputs()[1].name] = np.ones((BATCH_SIZE, 128), dtype=np.int64)
    if len(sess.get_inputs()) > 2:
        inp[sess.get_inputs()[2].name] = np.zeros((BATCH_SIZE, 128), dtype=np.int64)
    
    for _ in range(WARMUP):
        sess.run(None, inp)
    
    times = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        _ = sess.run(None, inp)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)  # ms
    
    avg_ms = sum(times) / len(times)
    ch_s = round(1000 / avg_ms * BATCH_SIZE, 1)
    
    return {
        "label": label,
        "providers": providers,
        "avg_ms": round(avg_ms, 1),
        "min_ms": round(min(times), 1),
        "max_ms": round(max(times), 1),
        "ch_s": ch_s,
    }

configs = [
    # (providers, opts, label)
    (["CPUExecutionProvider"], {"arena": False, "mem_pattern": False, "intra": 8, "inter": 1, "parallel": False}, "1️⃣ PRODUCTION (CPU, SEQUENTIAL, arena=False)"),
    (["CPUExecutionProvider"], {"arena": True, "mem_pattern": True, "intra": 8, "inter": 1, "parallel": True}, "2️⃣ CPU, PARALLEL, arena=True, ALL_OPT"),
    (["CPUExecutionProvider"], {"arena": True, "mem_pattern": True, "intra": 12, "inter": 2, "parallel": True}, "3️⃣ CPU, PARALLEL, intra=12"),
    (["AzureExecutionProvider"], {"arena": True, "mem_pattern": True, "intra": 8, "inter": 1, "parallel": True}, "4️⃣ AZURE ONLY, PARALLEL"),
    (["AzureExecutionProvider", "CPUExecutionProvider"], {"arena": True, "mem_pattern": True, "intra": 8, "inter": 1, "parallel": True}, "5️⃣ AZURE+CPU, PARALLEL"),
    (["AzureExecutionProvider", "CPUExecutionProvider"], {"arena": False, "mem_pattern": False, "intra": 8, "inter": 1, "parallel": False}, "6️⃣ AZURE+CPU, SEQUENTIAL, arena=False (как production)"),
]

results = []
for prov, opts, label in configs:
    print(f"\n{'─' * 60}")
    print(f"🏗️  {label}")
    print(f"   Провайдеры: {prov}")
    print(f"   Параметры: {opts}")
    r = run_benchmark(prov, opts, label)
    results.append(r)
    if r.get("error"):
        print(f"   ❌ {r['error']}")
    else:
        print(f"   ✅ {r['avg_ms']}ms avg | {r['ch_s']} ch/s")

# Итог
print("\n" + "=" * 70)
print("📊 ИТОГОВАЯ ТАБЛИЦА")
print("=" * 70)
print(f"{'Конфиг':<50} {'avg ms':<10} {'ch/s':<10}")
print("─" * 70)
for r in results:
    if r.get("error"):
        print(f"{r['label']:<50} {'ERROR':<10} {'0':<10}")
    else:
        print(f"{r['label']:<50} {r['avg_ms']:<10} {r['ch_s']:<10}")

print("\n" + "=" * 70)
print("📌 СРАВНЕНИЕ С PRODUCTION (30 ch/s)")
print("=" * 70)
best = max(results, key=lambda x: x['ch_s'])
print(f"Лучший конфиг: {best['label']} → {best['ch_s']} ch/s")
print(f"Текущий production (из логов): ~30 ch/s")
print(f"Потенциальный прирост: {best['ch_s']} / 30 = {best['ch_s']/30:.1f}x")
