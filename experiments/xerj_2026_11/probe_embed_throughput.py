"""Embedding throughput at realistic chunk length, measured on this machine.

Why this exists: 7 103 chunks at the observed 0.26 texts/s looked like hours.
The number matters only if it describes the model, not the call pattern. The
llama.cpp server here rejects any single input above its physical batch size
(512), so a 1 000-token text fails with HTTP 500 and the client falls back to
per-item retries. This probe uses DISTINCT texts of a known token length (the
same text repeated would be a cache hit and a fake speedup) and prints both.

Run: python experiments/xerj_2026_11/probe_embed_throughput.py
"""

import random
import string
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import httpx  # noqa: E402

URL = "http://127.0.0.1:8080/v1/embeddings"
TOKENIZER_URL = "http://127.0.0.1:8080/tokenize"
CHARS = 600  # ~450 tokens on the embeddinggemma tokenizer; the server caps a single input at 512
BATCHES = (1, 8, 32)


def random_code_like(chars: int, seed: int) -> str:
    rng = random.Random(seed)
    alphabet = string.ascii_letters + string.digits + " _(){}.,:=\n"
    return "".join(rng.choice(alphabet) for _ in range(chars))


def token_count(text: str) -> int:
    response = httpx.post(TOKENIZER_URL, json={"content": text}, timeout=60)
    return len(response.json().get("tokens", []))


def main() -> int:
    base = random_code_like(CHARS, seed=11)
    print(f"chars={len(base)} tokens={token_count(base)}")

    for batch in BATCHES:
        # Distinct texts: a repeated input could be cached by the server.
        texts = [base + f"\n# {i}" for i in range(batch)]
        started = time.perf_counter()
        response = httpx.post(URL, json={"input": texts}, timeout=1800)
        elapsed = time.perf_counter() - started
        if response.status_code != 200:
            print(f"n={batch:<3} status={response.status_code} {response.text[:140]}")
            continue
        print(
            f"n={batch:<3} wall={elapsed:7.2f}s  {batch / elapsed:7.2f} chunks/s  "
            f"per-chunk={elapsed / batch * 1000:6.0f} ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
