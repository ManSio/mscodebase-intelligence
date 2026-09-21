"""E2: порог ubatch=2048 токенов. Ищем скачок времени когда пачка пересекает
2048 токенов (llama-server разбивает на под-проходы).
batch по числу текстов N; тексты ~203 токена avg → 
N=1: ~200t   N=8: ~1600t (<2048, 1 проход)
N=12: ~2400t (>2048, 2 прохода)  <- порог!
Меряем per-request время и tok/s.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import statistics, time
import httpx, lancedb

DB = r"C:\Users\misha\AppData\Local\mscodebase\projects\bfe9644b\lancedb_v2\index_mscodebase_bfe9644b.db"
EMB = "http://127.0.0.1:8080/v1/embeddings"

db = lancedb.connect(DB)
df = db.open_table("codebase_chunks").to_pandas().head(64)
texts = [str(x) for x in df["text"].tolist()]
texts.sort(key=len)

# токены хотя бы для оценки
import subprocess
def _tok(t):
    import httpx as hx
    r = hx.Client(timeout=10).post("http://127.0.0.1:8080/tokenize", json={"content": t, "add_special": False})
    return int(r.json().get("count", 0))
toks = [_tok(x) for x in texts[:16]]
print(f"sample toks: avg={sum(toks)/len(toks):.0f} max={max(toks)}")

c = httpx.Client(timeout=60)
results = []
for N in (1, 4, 8, 10, 12, 16, 24, 32):
    batch = texts[:N]
    times = []
    for _ in range(3):
        t0 = time.time()
        r = c.post(EMB, json={"input": batch})
        times.append(time.time() - t0)
        if r.status_code != 200:
            print(f"N={N} HTTP {r.status_code}")
            break
    p50 = statistics.median(times)
    total_tok = sum(len(x) // 3 for x in batch)  # грубо ~3.4 chan/token на eng-коде
    tok_s = sum(len(x)/3.4 for x in batch) / p50
    results.append(f"N={N:2d} p50={p50*1000:6.1f}ms  ch/s={N/p50:5.1f}  ~tok/s={tok_s:5.0f}")

print("\n".join(results))
c.close()