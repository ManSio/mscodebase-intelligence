"""E13-нагрузчик: имитация index_project Phase 2 (реальный путь):
сортировка чанков по длине + batch=32 последовательно, как index_project_runner.
Гоняет 2000 реальных чанков из Локальнонi БД MSCodeBase. RAM снимает отдельный семплер.
"""
import sys, time
sys.stdout.reconfigure(encoding='utf-8')
import httpx, lancedb

DB = r"C:\Users\misha\AppData\Local\mscodebase\projects\bfe9644b\lancedb_v2\index_mscodebase_bfe9644b.db"
EMB = "http://127.0.0.1:8080/v1/embeddings"
BATCH = 32

db = lancedb.connect(DB)
df = db.open_table("codebase_chunks").to_pandas().head(2000)
texts = [str(x) for x in df["text"].tolist()]
texts.sort(key=len)   # как index_project_runner.py:344
total = len(texts)

c = httpx.Client(timeout=60)
t0 = time.time()
for i in range(0, total, BATCH):
    batch = texts[i:i+BATCH]
    r = c.post(EMB, json={"input": batch})
    if r.status_code != 200:
        print(f"HTTP {r.status_code} at {i}")
        break
    if i % (BATCH*10) == 0:
        el = time.time() - t0
        print(f"[{i}/{total}] avg={i/max(el,0.001):.1f} ch/s elapsed={el:.0f}s", flush=True)
print(f"DONE {total} chunks in {time.time()-t0:.1f}s = {total/(time.time()-t0):.1f} ch/s", flush=True)
c.close()