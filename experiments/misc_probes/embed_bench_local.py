"""Локальный тест инференса эмбеддинг-модели через llama-server (GGUF).

Запускает llama-server с BGE-M3 Q4_K_M GGUF (1024-dim, мультиязычный —
ближайший локально-запускаемый аналог Cohere embed-multilingual-v3.0,
чьи веса Cohere НЕ публикует) и прогоняет реальный инференс на 5 языках.

По §5.16 Windows: subprocess.Popen без capture_output, CREATE_NO_WINDOW.
"""

import subprocess
import sys
import time

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import httpx
import numpy as np

EXT = r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"
MODEL = EXT + r"\models\Bge-M3-568M-Q4_K_M.gguf"
SERVER = EXT + r"\llama_msvc\llama-server.exe"
PORT = 8080


def start_server():
    proc = subprocess.Popen(
        [
            SERVER,
            "--model",
            MODEL,
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--embeddings",
            "--pooling",
            "cls",
            "-b",
            "512",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )
    # wait for health
    for _ in range(60):
        try:
            r = httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=2)
            if r.status_code == 200:
                return proc
        except Exception:
            time.sleep(1)
    raise RuntimeError("server did not start")


def embed(texts, port=PORT):
    r = httpx.post(
        f"http://127.0.0.1:{port}/v1/embeddings",
        json={"input": texts, "encoding_format": "float"},
        timeout=30,
    )
    r.raise_for_status()
    return [d["embedding"] for d in r.json()["data"]]


def cosine(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def main():
    proc = start_server()
    try:
        samples = {
            "ru": "Функция для вычисления суммы двух чисел",
            "en": "Function to compute the sum of two numbers",
            "de": "Funktion zur Berechnung der Summe zweier Zahlen",
            "zh": "计算两个数字之和的函数",
            "fr": "Fonction pour calculer la somme de deux nombres",
            "code": "def add(a, b): return a + b",
        }
        labels = list(samples.keys())
        texts = list(samples.values())

        t0 = time.perf_counter()
        vecs = embed(texts)
        dt = time.perf_counter() - t0

        dim = len(vecs[0])
        norms = [float(np.linalg.norm(v)) for v in vecs]
        print(f"DIM={dim}")
        print(f"BATCH={len(vecs)}  TIME={dt * 1000:.1f} ms  ({len(vecs) / dt:.2f} txt/s)")
        print(f"NORMS min={min(norms):.3f} max={max(norms):.3f}")
        print("--- cross-lingual similarity (vs EN) ---")
        en = vecs[labels.index("en")]
        for lab in labels:
            if lab == "en":
                continue
            print(f"  en~{lab}: {cosine(en, vecs[labels.index(lab)]):.4f}")
        print("--- semantic vs code ---")
        print(f"  en~code: {cosine(en, vecs[labels.index('code')]):.4f}")
        print(f"  ru~code: {cosine(vecs[labels.index('ru')], vecs[labels.index('code')]):.4f}")
    finally:
        proc.terminate()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)
