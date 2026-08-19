"""E-07 — сьют эквивалентности транспортов: stdio vs Streamable HTTP.

DoD Фазы 3 (план §3): "один и тот же запрос через stdio и HTTP возвращает
идентичный JSON для репрезентативного подмножества тулов".

Подход (live, не моки): один и тот же сервер поднимается ДВАЖДЫ — по stdio и по
Streamable HTTP; один и тот же MCP-клиент (mcp SDK) делает репрезентативные
пробы через оба транспорта, выхлоп сериализуется в canonical JSON и сравнивается.

Два режима:
  --toy     минимальный FastMCP-сервер (_e07_toy_server.py) — валидация гарнесса
            без тяжёлого движка (без embedder/PID-lock). Можно гонять live всегда.
  (default) реальный движок (create_mcp_server): stdio `python -m src.main` +
            HTTP `uvicorn src.remote_main:app`. Пробы без embed-зависимости.
            Стабильнее всего на чистом раннере (CI Ubuntu) или при остановленном
            основном MCP — иначе E-07 движок не захватит PID-lock эмбеддера
            (деградация), пробы-без-embed отвечают корректно.

Запуск:
  python experiments/universal-engine/e07_transport_equiv.py --toy [--port 8092]
  python experiments/universal-engine/e07_transport_equiv.py [--port 8090]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_PORT = 8090
START_TIMEOUT = 90.0
PROBE_TIMEOUT = 30.0


def _base_env() -> dict:
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(ROOT))
    env.pop("MSCODEBASE_REMOTE_TOKEN", None)  # auth off — тест транспорта, не auth
    return env


def _engine_env(data_dir: Path) -> dict:
    env = _base_env()
    env["MSCODEBASE_DATA_DIR"] = str(data_dir)
    env["DISABLE_ONNX_FALLBACK"] = "1"  # не грузить ONNX-модели
    return env


# ── пробы: (имя, метод, аргументы) ─────────────────────────────────────────

def _engine_probes() -> dict:
    return {
        "unknown-method": ("no.such.tool", {}),
        "counters": ("get_runtime_counters", {}),
        "bad-args": ("get_runtime_counters", {"bogus": 1}),
    }


def _toy_probes() -> dict:
    return {
        "ping-result": ("ping", {"prefix": "probe"}),
        "bad-args": ("ping", {"bogus": 1}),
    }


async def _run_transport(kind: str, mode: str, data_dir: Path, port: int) -> dict:
    """Запускает сервер в нужном транспорте и собирает canonical-выхлоп проб."""
    from mcp import ClientSession

    if kind == "stdio":
        from mcp.client.stdio import StdioServerParameters, stdio_client

        args = _toy_stdio_cmd() if mode == "--toy" else [sys.executable, "-m", "src.main"]
        params = StdioServerParameters(
            command=args[0], args=args[1:], cwd=str(ROOT),
            env=_engine_env(data_dir) if mode != "--toy" else _base_env(),
        )
        cm = stdio_client(params)
    else:
        from mcp.client.streamable_http import streamablehttp_client

        proc = _spawn_http(mode, data_dir, port)
        url = f"http://127.0.0.1:{port}/mcp"
        try:
            await _wait_http(port, mode, proc)
            cm = streamablehttp_client(url)
        except Exception:
            proc.terminate()
            raise

    results = {}
    try:
        async with cm as streams:
            if kind == "stdio":
                read, write = streams
            else:
                read, write, _ = streams
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), PROBE_TIMEOUT)
                probes = _toy_probes() if mode == "--toy" else _engine_probes()
                for name, (method, args) in probes.items():
                    results[name] = await _probe(session, method, args)
        return results
    finally:
        if kind != "stdio" and "proc" in locals():
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _toy_stdio_cmd() -> list:
    return [sys.executable, str(ROOT / "experiments" / "universal-engine" / "_e07_toy_server.py")]


def _spawn_http(mode: str, data_dir: Path, port: int) -> subprocess.Popen:
    if mode == "--toy":
        cmd = [sys.executable, str(ROOT / "experiments" / "universal-engine" / "_e07_toy_server.py"),
               "--http", str(port)]
        env = _base_env()
    else:
        cmd = [sys.executable, "-m", "uvicorn", "src.remote_main:app",
               "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"]
        env = _engine_env(data_dir)
    return subprocess.Popen(
        cmd, cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


async def _probe(session, method: str, args: dict) -> dict:
    try:
        r = await asyncio.wait_for(session.call_tool(method, args), PROBE_TIMEOUT)
        return {"ok": _canon(r)}
    except Exception as e:  # noqa: BLE001 — ловим любой метод/transport error
        err = getattr(e, "error", None)
        if err is not None and hasattr(err, "code"):
            return {"error": {"code": err.code, "message": err.message}}
        return {"error_type": type(e).__name__, "str": str(e)}


def _canon(r) -> dict:
    try:
        return json.loads(r.model_dump_json())
    except Exception:  # noqa: BLE001
        content = getattr(r, "content", None)
        if content is not None:
            return {"content": [getattr(c, "text", None) for c in content]}
        return {"raw": repr(r)}


async def _wait_http(port: int, mode: str, proc: subprocess.Popen) -> None:
    """Ждём, пока http-сервер слушает. Готовность = ЛЮБОЙ HTTP-ответ.

    engine-mode: у remote_main есть auth-exempt /healthz (200);
    toy-mode: FastMCP-приложение смонтировано в корне (нет /healthz) — берём "/".
    """
    if mode == "--toy":
        ready_url = f"http://127.0.0.1:{port}/"
    else:
        ready_url = f"http://127.0.0.1:{port}/healthz"
    st = time.monotonic()
    while time.monotonic() - st < START_TIMEOUT:
        if proc.poll() is not None:
            raise RuntimeError(f"http server exited early: code={proc.returncode}")
        try:
            httpx.get(ready_url, timeout=2.0)
            return
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError(f"http server not ready ({ready_url}) in {START_TIMEOUT}s")


def _compare(name: str, a: dict, b: dict) -> bool:
    ok = a == b
    print(f"  {'✅' if ok else '❌'} {name}: {'identical' if ok else 'DIFFER'}")
    if not ok:
        print(f"      stdio: {json.dumps(a, ensure_ascii=False)[:220]}")
        print(f"      http : {json.dumps(b, ensure_ascii=False)[:220]}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="E-07 transport equivalence stdio vs HTTP")
    ap.add_argument("--toy", action="store_true", help="minimal FastMCP server (no engine)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    mode = "--toy" if args.toy else ""
    label = "toy FastMCP" if args.toy else "real engine (create_mcp_server)"
    td = Path(tempfile.mkdtemp(prefix="mscodebase_e07_"))
    stdio_dir, http_dir = td / "stdio", td / "http"
    stdio_dir.mkdir(), http_dir.mkdir()

    print("=" * 72)
    print(f"E-07: transport equivalence stdio vs Streamable HTTP ({label})")
    print("=" * 72)

    stdio = asyncio.run(_run_transport("stdio", mode, stdio_dir, args.port))
    http = asyncio.run(_run_transport("http", mode, http_dir, args.port))

    names = stdio.keys() | http.keys()
    checks = [_compare(n, stdio.get(n), http.get(n)) for n in sorted(names)]
    ok = all(checks)
    print(f"\nE-07 VERDICT: {'PASSED' if ok else 'PARTIAL'} ({sum(checks)}/{len(checks)})")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — верхний guard эксперимента
        import traceback

        traceback.print_exc()
        sys.exit(1)
