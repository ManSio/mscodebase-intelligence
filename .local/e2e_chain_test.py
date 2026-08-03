"""E2E-проверка цепочки: embed (UTF-8) -> rerank -> поиск через MCP HTTP-эндпоинты."""
import sys
import httpx

BASE_EMBED = "http://127.0.0.1:8080"
BASE_RERANK = "http://127.0.0.1:8081"


def main() -> int:
    # 1. Embedder с кириллицей (реальный UTF-8, не артефакт curl/GitBash)
    r = httpx.post(f"{BASE_EMBED}/v1/embeddings",
                   json={"input": ["Тест эмбеддера с кириллицей", "second input"]},
                   timeout=20)
    assert r.status_code == 200, f"EMBED HTTP {r.status_code}: {r.text[:200]}"
    data = r.json()
    dims = len(data["data"][0]["embedding"])
    n = len(data.get("data", []))
    print(f"[1] EMBED  status={r.status_code} dims={dims} n={n}")

    # 2. Reranker (кириллица)
    r2 = httpx.post(f"{BASE_RERANK}/rerank",
                    json={"query": "как запустить тесты",
                          "texts": ["pytest tests", "словарь", "рандом"]},
                    timeout=20)
    assert r2.status_code == 200, f"RERANK HTTP {r2.status_code}: {r2.text[:200]}"
    scores = [round(x["score"], 3) for x in r2.json()]
    print(f"[2] RERANK status={r2.status_code} scores={scores}")
    assert scores[0] > scores[1] > scores[2], "Ранжирование не упорядочено — подозрительно"

    # 3. Health
    h = httpx.get(f"{BASE_EMBED}/health", timeout=10)
    print(f"[3] HEALTH status={h.status_code} body={h.text[:60]}")

    print("E2E CHAIN: PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
