"""
Эксперимент: сравнение конфигов ONNX + normalize.
Работает без MCP/Zed. Только модель + чанки.
"""
import sys, os, time, json, numpy as np
from pathlib import Path
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

EXT_DIR = Path(os.environ.get("EXT_DIR", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
MODEL_DIR = EXT_DIR / ".codebase_models" / "onnx" / "multilingual-e5-small-int8"
MODEL_FILE = MODEL_DIR / "model_quantized.onnx"

# 1. Загружаем токенизатор
from tokenizers import Tokenizer
tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=128)
tokenizer.enable_truncation(max_length=128)

# 2. Чанки — реальные из проекта (первые 200 строк из indexer.py)
with open(os.path.join(os.path.dirname(__file__), '..', 'src', 'core', 'indexing', 'indexer.py'), 'r', encoding='utf-8') as f:
    code = f.read()
# Разбиваем на чанки как IndexParser (~800 символов с перекрытием 200)
chunks = []
for i in range(0, len(code), 600):
    chunk = code[i:i+800]
    if len(chunk) > 50:
        chunks.append(chunk)
chunks = chunks[:50]  # 50 чанков для теста
print(f"Загружено {len(chunks)} чанков")

# 3. Тексты для эмбеддинга (с passage: prefix)
texts = [f"passage: {c}" for c in chunks]
print(f"Средняя длина текста: {sum(len(t) for t in texts)//len(texts)} символов")

# 4. Тестовые запросы (реальные поисковые запросы)
queries = [
    "def index_project",
    "class RemoteEmbedder",
    "embed_batch onnx session",
    "create_index ivf flat",
    "parse_file tree-sitter",
]
query_texts = [f"query: {q}" for q in queries]

# 5. Функция эмбеддинга (как в production)
import onnxruntime as ort

def make_session(graph_opt, intra=8, seq=True):
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = intra
    opts.graph_optimization_level = graph_opt
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL if seq else ort.ExecutionMode.ORT_PARALLEL
    opts.enable_cpu_mem_arena = False
    opts.enable_mem_pattern = False
    opts.enable_mem_reuse = True
    return ort.InferenceSession(str(MODEL_FILE), sess_options=opts, providers=['CPUExecutionProvider'])

def encode(session, texts, normalize=False):
    prefixed = texts
    enc = tokenizer.encode_batch(prefixed, add_special_tokens=True)
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    inputs = {"input_ids": ids, "attention_mask": mask}
    if len(session.get_inputs()) > 2:
        tt = np.array([getattr(e, "type_ids", None) or [0]*len(e.ids) for e in enc], dtype=np.int64)
        inputs["token_type_ids"] = tt
    outputs = session.run(None, inputs)
    token_emb = outputs[0]
    mask_exp = np.expand_dims(mask, -1).astype(float)
    sum_emb = np.sum(token_emb * mask_exp, 1)
    sum_mask = np.clip(np.sum(mask_exp, 1), a_min=1e-9, a_max=None)
    emb = sum_emb / sum_mask
    if normalize:
        norm = np.linalg.norm(emb, axis=1, keepdims=True)
        norm = np.where(norm == 0, 1e-12, norm)
        emb = emb / norm
    return emb

# 6. Эксперимент: сравниваем конфиги
configs = [
    ("BASIC SEQ", ort.GraphOptimizationLevel.ORT_ENABLE_BASIC, True, False),
    ("ALL SEQ (текущий фикс)", ort.GraphOptimizationLevel.ORT_ENABLE_ALL, True, False),
    ("ALL SEQ + L2 normalize", ort.GraphOptimizationLevel.ORT_ENABLE_ALL, True, True),
]

print("\n" + "=" * 70)
print("🧪 ЭКСПЕРИМЕНТ 1: Скорость эмбеддинга (batch=4, 50 чанков)")
print("=" * 70)

for label, opt, seq, norm in configs:
    sess = make_session(opt, intra=8, seq=seq)
    # Warmup
    encode(sess, texts[:4])
    # Замер
    times = []
    for i in range(0, len(texts), 4):
        batch = texts[i:i+4]
        t0 = time.perf_counter()
        encode(sess, batch, normalize=norm)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    avg_ms = sum(times) / len(times)
    ch_s = 1000 / avg_ms * 4
    print(f"  {label:<25} {avg_ms:.0f}ms/батч = {ch_s:.0f} ch/s")

print("\n" + "=" * 70)
print("🧪 ЭКСПЕРИМЕНТ 2: Качество поиска (ранжирование)")
print("=" * 70)

# Эмбеддим чанки с BASIC (как в старом production) и ALL+normalize
sess_basic = make_session(ort.GraphOptimizationLevel.ORT_ENABLE_BASIC, seq=True)
sess_all = make_session(ort.GraphOptimizationLevel.ORT_ENABLE_ALL, seq=True)

chunk_emb_basic = encode(sess_basic, texts, normalize=False)
chunk_emb_all = encode(sess_all, texts, normalize=False)
chunk_emb_all_norm = encode(sess_all, texts, normalize=True)

for q_text, q_label in zip(query_texts, queries):
    q_basic = encode(sess_basic, [q_text], normalize=False)[0]
    q_all = encode(sess_all, [q_text], normalize=False)[0]
    q_all_norm = encode(sess_all, [q_text], normalize=True)[0]
    
    # cosine similarity (для нормализованных = dot product)
    def score(q, chunks):
        dots = np.dot(chunks, q)
        q_n = np.linalg.norm(q)
        c_n = np.linalg.norm(chunks, axis=1)
        return dots / (q_n * c_n + 1e-12)
    
    sim_basic = score(q_basic, chunk_emb_basic)
    sim_all = score(q_all, chunk_emb_all)
    sim_all_norm = np.dot(chunk_emb_all_norm, q_all_norm)  # normalize уже сделано
    
    # Топ-3
    top_b = np.argsort(-sim_basic)[:3]
    top_a = np.argsort(-sim_all)[:3]
    top_n = np.argsort(-sim_all_norm)[:3]
    
    print(f"\n  Запрос: {q_label}")
    print(f"  {'Ранг':<5} {'BASIC (top)':<40} {'ALL (top)':<40} {'ALL+NORM (top)':<40}")
    print(f"  {'─'*5} {'─'*40} {'─'*40} {'─'*40}")
    for r in range(3):
        b = chunks[top_b[r]][:60] if r < len(top_b) else "-"
        a = chunks[top_a[r]][:60] if r < len(top_a) else "-"
        n = chunks[top_n[r]][:60] if r < len(top_n) else "-"
        print(f"  #{r+1:<3} {b:<40} {a:<40} {n:<40}")
    
    # Проверка: совпадают ли топ-1
    same1 = "✅" if top_b[0] == top_n[0] else "❌"
    same3 = "✅" if set(top_b[:3]) == set(top_n[:3]) else "❌"
    print(f"  Совпадение топ-1: {same1}  |  топ-3: {same3}")
