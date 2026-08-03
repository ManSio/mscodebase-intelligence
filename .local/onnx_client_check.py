"""Проверка ONNX через реальный discover-or-launch путь (как в MCP-сервере)."""
import httpx

from src.core.embedder.onnx_client import get_onnx_client


def main() -> int:
    client = get_onnx_client(port=9876, model_name="multilingual-e5-small-int8")
    ok = client.ensure_server_running()
    print(f"[1] ensure_server_running: {ok}")
    assert ok, "ONNX server не запустился через клиент"

    r = httpx.post("http://127.0.0.1:9876/embed",
                   json={"text": "тест onnx кириллица через клиент"}, timeout=60)
    print(f"[2] embed status={r.status_code}")
    assert r.status_code == 200, r.text[:200]
    vec = r.json().get("vector", [])
    print(f"[3] dim={len(vec)} first3={vec[:3]}")
    assert len(vec) == 384, f"ожидал 384 dim, получил {len(vec)}"
    print("ONNX CLIENT PATH: PASSED")
    return 0


if __name__ == "__main__":
    import traceback
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
