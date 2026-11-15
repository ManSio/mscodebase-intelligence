"""Guard: Streamable HTTP app принимает запрос с не-localhost `Host`.

Паритет 1.x/2.x. На 2.x `streamable_http_app(transport_security=None)` включает
DNS-rebinding защиту со списком `127.0.0.1 / localhost / [::1]`, и remote-клиент
по `http://<ip>:8089/mcp` получает 421 `Invalid Host header` ещё до Bearer-auth.
Периметр держит `remote_main` (Bearer), поэтому защита выключена явно.

Тест строит настоящий ASGI-app (не фейковый `/mcp/inner`) и шлёт `initialize`
с `Host: 192.0.2.55:8089` (RFC 5737, TEST-NET-1).
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP  # шим: на 2.x это MCPServer
from starlette.testclient import TestClient

from src.mcp.transport.streamable_http import _build_streamable_http_app

REMOTE_HOST = "192.0.2.55:8089"
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "host-guard", "version": "0"},
    },
}


def _post(client: TestClient, host: str):
    return client.post(
        "/",
        json=INITIALIZE,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Host": host,
        },
    )


def test_non_localhost_host_is_not_rejected():
    app, _ = _build_streamable_http_app(FastMCP("host-guard"))
    with TestClient(app) as client:
        resp = _post(client, REMOTE_HOST)
    assert resp.status_code != 421, f"DNS-rebinding защита отбила {REMOTE_HOST}: {resp.text}"
    assert resp.status_code == 200, resp.text


def test_localhost_host_still_works():
    app, _ = _build_streamable_http_app(FastMCP("host-guard"))
    with TestClient(app) as client:
        resp = _post(client, "127.0.0.1:8089")
    assert resp.status_code == 200, resp.text
