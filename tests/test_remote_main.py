"""Тесты Фазы 3 Universal Engine: remote_main (Streamable HTTP вход).

Проверяем auth + /healthz + mount /mcp на легковесном фейк-app
(без построения реального create_mcp_server). Bearer-auth:
- /healthz открыт без токена;
- все прочие пути требуют Authorization: Bearer <token> (401 иначе);
- токен пустой = auth выключен.
"""

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.remote_main import build_app


def _fake_mcp_app() -> Starlette:
    async def _echo(request):
        return JSONResponse({"ok": True})

    return Starlette(routes=[Route("/inner", _echo)])


def _client(token: str) -> TestClient:
    return TestClient(build_app(mcp_app=_fake_mcp_app(), token=token))


def test_healthz_open_without_auth():
    c = _client("SECRET")
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_mcp_requires_bearer():
    c = _client("SECRET")
    assert c.get("/mcp/inner").status_code == 401
    r = c.get("/mcp/inner", headers={"Authorization": "Bearer SECRET"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_wrong_token_rejected():
    c = _client("SECRET")
    assert c.get("/mcp/inner", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_no_token_means_no_auth():
    c = _client("")
    assert c.get("/mcp/inner").status_code == 200


def test_healthz_ignores_auth_even_no_token():
    # /healthz не auth'ится при включённом токене
    c = _client("SECRET")
    assert c.get("/healthz").status_code == 200
