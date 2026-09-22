"""Малость 2: токены корпуса — отделяем «число текстов» от «token-потолка».
Считаем llama-токены реального корпуса и пересчитываем ch/s → tok/s.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import statistics
import httpx
import lancedb

DB = r"C:\Users\misha\AppData\Local\mscodebase\projects\bfe9644b\lancedb_v2\index_mscodebase_bfe9644b.db"
TOK_URL = "http://127.0.0.1:8080/tokenize"

db = lancedb.connect(DB)
t = db.open_table("codebase_chunks")
df = t.to_pandas().head(640)
texts = [str(x) for x in df["text"].tolist()]
texts.sort(key=len)

def tok(client, text):
    r = client.post(TOK_URL, json={"content": text, "add_special": False}, timeout=5.0)
    return int(r.json().get("count", len(r.json().get("tokens", []))))

c = httpx.Client(timeout=30)
toks = [tok(c, x) for x in texts]
c.close()

total = sum(toks)
print(f"texts={len(texts)} total_tokens={total} avg={total/len(texts):.0f} "
      f"p90={sorted(toks)[int(len(toks)*0.9)]} max={max(toks)}")
# Скорости из эксперимента 1 (18 ch/s raw): tok/s
print(f"[raw POST 18ch/s] -> {18*total/len(texts):.0f} tok/s")
print(f"[E10 sustained 11.9ch/s] -> {11.9*total/len(texts):.0f} tok/s")
# Пересчёт: если сустейн ~X tok/s, сколько ch/s даст этот корпус
for toks in (2000, 3000, 4000):
    print(f"  if sustained {toks} tok/s -> {toks/(total/len(texts)):.0f} ch/s on this corpus")