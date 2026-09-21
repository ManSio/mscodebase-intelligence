"""Exp: real-path llama_cpp embed vs raw POST — где пропадают ch/s.

Контекст: микро-бенч T3 (156 ch/s) бил HTTP /v1/embeddings напрямую с
коротким синтетическим корпусом (~30 chars). Реальный путь embed_batch()
перед embed гоняет _truncate_for_llama() — на каждый текст ДЛИННЕЕ 256
символов отдельный HTTP /tokenize round-trip (на пачку 32 = до 32 HTTP).

Вопрос: сколько % времени цикла index_project_runner уходит на truncation
и насколько реальная дорога embed_batch медленнее голого POST.

Руки (контрольная группа — один реальный корпус из индекса, одна сессия):
  A) raw POST /v1/embeddings batch=32 (T3-копия, БЕЗ truncation)
  B) real embed_batch() llama_cpp (С truncation), как в проде
  C) только _truncate_for_llama() на том же корпусе (стоимость токенизации)
  D) zero-vector / validity check для всех векторов руки B
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import time
import statistics

import httpx
import lancedb

DB = r"C:\Users\misha\AppData\Local\mscodebase\projects\bfe9644b\lancedb_v2\index_mscodebase_bfe9644b.db"
N_CHUNKS = 640     # 20 пачек по 32
BATCH = 32
PORT = 8080
EMBED_URL = f"http://127.0.0.1:{PORT}/v1/embeddings"
TOK_URL = f"http://127.0.0.1:{PORT}/tokenize"
MAX_TOKENS = 480
MIN_CHARS = 256


def load_chunks(limit: int):
    db = lancedb.connect(DB)
    t = db.open_table("codebase_chunks")
    df = t.to_pandas().head(limit)
    texts = [str(x) for x in df["text"].tolist()]
    # сортировка как в index_project_runner (по длине)
    texts.sort(key=len)
    return texts


def llama_token_count(client, text: str) -> int:
    try:
        r = client.post(TOK_URL, json={"content": text, "add_special": False}, timeout=5.0)
        if r.status_code == 200:
            data = r.json()
            return int(data.get("count", len(data.get("tokens", []))))
    except Exception:
        pass
    return -1


def truncate_for_llama(client, texts):
    """Дословная реплика remote_embedder._truncate_for_llama (line 200-238)."""
    out = []
    tokenize_calls = 0
    for t in texts:
        if len(t) <= MIN_CHARS:
            out.append(t)
            continue
        tokenize_calls += 1
        n = llama_token_count(client, t)
        if n < 0:
            out.append(t)
            continue
        if n <= MAX_TOKENS:
            out.append(t)
            continue
        cut = t
        for _ in range(4):
            new_len = int(len(cut) * (MAX_TOKENS / n) * 0.8)
            if new_len >= len(cut) or new_len < 1:
                break
            cut = cut[:new_len]
            n = llama_token_count(client, cut)
            tokenize_calls += 1
            if n <= MAX_TOKENS:
                break
        out.append(cut)
    return out, tokenize_calls


def vec_norm(v):
    return sum(x * x for x in v) ** 0.5


def run_arm(client, texts, label):
    """Прокачивает ВСЕ N_CHUNKS пачками по BATCH, возвращает ch/s и метрики."""
    t0 = time.time()
    batch_times = []
    zero = 0
    total = 0
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i + BATCH]
        tb0 = time.time()
        r = client.post(EMBED_URL, json={"input": batch}, timeout=120)
        dt = time.time() - tb0
        batch_times.append(dt)
        if r.status_code != 200:
            print(f"  [{label}] HTTP {r.status_code} at {i}")
            continue
        data = sorted(r.json().get("data", []), key=lambda x: x.get("index", 0))
        for d in data:
            v = d["embedding"]
            total += 1
            if all(x == 0.0 for x in v):
                zero += 1
    el = time.time() - t0
    n = len(texts)
    ch_s = n / el if el > 0 else 0
    print(f"[{label}] {n}ch in {el:.1f}s = {ch_s:.0f} ch/s | "
          f"p50_batch={statistics.median(batch_times)*1000:.0f}ms | "
          f"zero_vec={zero}/{total} ({(zero/total)*100 if total else 0:.1f}%)")
    return ch_s, el, zero, total


def main():
    print("=== Exp: real llama_cpp embed path vs raw POST ===")
    texts = load_chunks(N_CHUNKS)
    lens = [len(t) for t in texts]
    over256 = sum(1 for l in lens if l > 256)
    print(f"corpus: {len(texts)} chunks | len p50={statistics.median(lens)} "
          f"p90={sorted(lens)[int(len(lens)*0.9)]} max={max(lens)} | >256chars={over256}/{len(texts)}")

    # прогрев
    hw = httpx.Client(timeout=120)
    hw.post(EMBED_URL, json={"input": ["warmup"]})

    # ARM C: стоимость truncation отдельно
    tc0 = time.time()
    _, tok_calls = truncate_for_llama(hw, texts)
    tc = time.time() - tc0
    print(f"ARM C truncation only: {len(texts)} texts, {tok_calls} /tokenize HTTP calls "
          f"in {tc:.1f}s ({tc/len(texts)*1000:.0f}ms/text avg)")

    # ARM A: raw POST без truncation (T3-копия)
    run_arm(hw, texts, "A raw POST (+trunc none)")

    # ARM B: с truncation перед каждой пачкой (реальный путь)
    t0 = time.time()
    batch_times = []
    zero = 0
    total = 0
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i + BATCH]
        truncated, _ = truncate_for_llama(hw, batch)
        tb0 = time.time()
        r = hw.post(EMBED_URL, json={"input": truncated}, timeout=120)
        dt = time.time() - tb0
        batch_times.append(dt)
        if r.status_code != 200:
            print(f"  [B] HTTP {r.status_code} at {i}")
            continue
        data = sorted(r.json().get("data", []), key=lambda x: x.get("index", 0))
        for d in data:
            v = d["embedding"]
            n = vec_norm(v)
            total += 1
            if all(x == 0.0 for x in v):
                zero += 1
            elif n < 1e-6:
                print(f"  [B] near-zero norm {n:.2e} at {i}")
    el = time.time() - t0
    n = len(texts)
    print(f"[B trunc+embed] {n}ch in {el:.1f}s = {n/el:.0f} ch/s | "
          f"p50_batch={statistics.median(batch_times)*1000:.0f}ms | "
          f"zero_vec={zero}/{total}")

    hw.close()
    print("=== done ===")


if __name__ == "__main__":
    main()