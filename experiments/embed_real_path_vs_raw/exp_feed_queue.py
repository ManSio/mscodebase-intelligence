"""E4: «правильная подача в очередь» — размер пачки по ТОКЕНАМ под ubatch=2048,
варьируя длину чанков и параллельность.

Гипотеза владельца: узкое место не в embedder, а в том КАК подаются пачки.
Сейчас: BATCH_SIZE=32 текстов × ~203 ток = ~6500 токенов на запрос
(сервер с ubatch=2048 сам делит на под-проходы). 
Гипотеза: если подавать пачками ~=2048 токенов (одна ubatch-порция) — 
tok/s вырастет, т.к. каждый запрос = 1 проход дешифровки, нет накладных на чанкинг.

План:
- Корпус: реальные чанки из DMDB, средняя ~203 токена.
- Меряем tok/s и ch/s для пачек, собранных по целевому БЮДЖЕТУ токенов:
    512, 1024, 2048, 4096 (4 прохода), 8192 (4)
- Три длины чанков: короткие (~40 ток), средние (~100), длинные (~203).
- Concurrency: 1 запрос за раз (как в цикле) vs 3 параллельных (параллельность).

Вывод: оптимальный target_tokens и есть ли выигрыш от параллельности.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import statistics, time
from concurrent.futures import ThreadPoolExecutor
import httpx, lancedb

DB = r"C:\Users\misha\AppData\Local\mscodebase\projects\bfe9644b\lancedb_v2\index_mscodebase_bfe9644b.db"
EMB = "http://127.0.0.1:8080/v1/embeddings"

db = lancedb.connect(DB)
df = db.open_table("codebase_chunks").to_pandas()
texts = [str(x) for x in df["text"].tolist()]

# оценка токенов: ~3.9 chars/token (EN-код)
CHARS_PER_TOKEN = 3.9

def tok_est(t): return max(1, int(len(t) / CHARS_PER_TOKEN))

# Нарезаем корпус по целевым длинам (в токенах)
def make_corpus(target_tok, unit="char"):
    out = []
    for t in texts[:400]:
        total_chars = int(target_tok * CHARS_PER_TOKEN)
        while len(t) >= total_chars and len(out) < 200:
            out.append(t[:total_chars])
            t = t[total_chars:]
    out.extend(texts[:200])
    return out

def build_batches_by_tokens(corpus, budget_tokens, max_items=64):
    """Собирает пачки так, что суммарные токены <= budget. Жадный непрерывный."""
    batches = []
    cur, cur_tok = [], 0
    for t in corpus:
        tk = tok_est(t)
        if cur and cur_tok + tk > budget_tokens:
            batches.append(cur); cur, cur_tok = [], 0
        cur.append(t); cur_tok += tk
        if len(cur) >= max_items:
            batches.append(cur); cur, cur_tok = [], 0
    if cur: batches.append(cur)
    return batches

def run_batches(client, batches, nw=1):
    times, tk_total = [], 0
    t0 = time.time()
    if nw == 1:
        for b in batches:
            t1 = time.time()
            r = client.post(EMB, json={"input": b})
            times.append(time.time() - t1)
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            tk_total += sum(tok_est(x) for x in b)
    else:
        def one(b):
            t1 = time.time()
            r = httpx.Client(timeout=120).post(EMB, json={"input": b})
            return (r.status_code, time.time() - t1, sum(tok_est(x) for x in b))
        with ThreadPoolExecutor(max_workers=nw) as ex:
            res = list(ex.map(one, batches))
        for status, dt, tk in res:
            if status != 200: return None, f"HTTP {status}"
            times.append(dt); tk_total += tk
    elapsed = time.time() - t0
    return (len(batches), sum(len(b) for b in batches), tk_total, elapsed, statistics.median(times)), None

c = httpx.Client(timeout=120)
print(f"{'чанк_токен':>10} {'budget':>6} {'пачек':>5} {'чанков':>6} {'p50ms':>7} {'tok/s':>7} {'ch/s':>6}")
for chunk_tok in (40, 100, 203):
    corpus = make_corpus(chunk_tok)
    for budget in (512, 1024, 2048, 4096, 8192):
        batches = build_batches_by_tokens(corpus, budget)
        batches = batches[:20]
        for nw in (1, 3):
            res, err = run_batches(c, batches, nw)
            if err:
                print(f"{chunk_tok:>10} {budget:>6}         конк={nw} ERR {err}")
                continue
            n_batch, n_ch, tk, el, p50 = res
            print(f"{chunk_tok:>10} {budget:>6} {n_batch:>5} {n_ch:>6} {p50:>7.0f} {tk/el:>7.0f} {n_ch/el:>6.1f}  конк={nw}")
c.close()