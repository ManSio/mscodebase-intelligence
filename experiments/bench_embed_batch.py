"""
A/B-эксперимент T3 (arm A/B): benchmark batch-размера embedder'а.
ОБЩИЙ скрипт для обеих рук — arm B запускает БЕЗ изменений (сравнимость).

Метод (задание T3):
- Корпус: 64 текста средней длины (детерминированный).
- batch ∈ {8, 16, 32, 64}; N=3 повтора; медиана.
- Метрики: ch/s (текстов/сек), p50 latency на запрос, errors.
- Реальный путь вызова: POST http://127.0.0.1:8080/v1/embeddings (llama.cpp).
"""

import json
import statistics
import sys
import time
import urllib.request

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

URL = "http://127.0.0.1:8080/v1/embeddings"
CORPUS = [
    f"Строка {i}: компонент системы индексации исходного кода — парсинг синтаксических "
    "деревьев, семантический поиск по репозиторию и граф вызовов между символами проекта."
    for i in range(64)
]


def embed(batch: int):
    chunks = [CORPUS[i : i + batch] for i in range(0, 64, batch)]
    t0 = time.perf_counter()
    errors = 0
    latencies = []
    for chunk in chunks:
        body = json.dumps({"input": chunk}).encode("utf-8")
        req = urllib.request.Request(
            URL, data=body, headers={"Content-Type": "application/json"}
        )
        s = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read().decode("utf-8"))
            n = len(resp["data"])
            if n != len(chunk):
                errors += 1
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"  ERROR batch={batch}: {e}", file=sys.stderr)
        latencies.append(time.perf_counter() - s)
    total = time.perf_counter() - t0
    return total, latencies, errors


def main():
    print(f"URL: {URL} | корпус: {len(CORPUS)} текстов | повторов: 3", flush=True)
    print("warmup...", flush=True)
    embed(8)  # прогреваем (первый вызов холодный)

    print("batch,rep,total_s,ch_s,p50_req_ms,errors", flush=True)
    results: dict = {}
    for batch in (8, 16, 32, 64):
        speeds, p50s, errs = [], [], 0
        for rep in range(1, 4):
            total, lat, e = embed(batch)
            ch = len(CORPUS) / total
            speeds.append(ch)
            p50s.append(statistics.median(lat) * 1000)
            errs += e
            print(
                f"{batch},{rep},{total:.3f},{ch:.2f},{statistics.median(lat) * 1000:.1f},{e}",
                flush=True,
            )
        results[batch] = (statistics.median(speeds), statistics.median(p50s), errs)

    print("\n=== MEDIAN (по 3 повторам) ===", flush=True)
    for batch, (ch, p50, e) in sorted(results.items()):
        print(f"batch={batch:>3}: ch/s={ch:.2f}, p50_req={p50:.1f}ms, errors={e}", flush=True)
    best = max(results, key=lambda b: results[b][0])
    print(f"\nBEST ch/s: batch={best} ({results[best][0]:.2f})", flush=True)
    ref = results[32][0]
    print(f"Отношение к прод-настройке batch=32: best/32 = {results[best][0] / ref:.3f}x", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)
