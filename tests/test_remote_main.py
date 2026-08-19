"""Тесты Фазы 3 Universal Engine: remote_main (Streamable HTTP вход).

Проверяем auth + /healthz + mount /mcp + rate-limit + circuit breaker
на легковесном фейк-app (без построения реального create_mcp_server).
Гейт (снаружи внутрь): rate-limit (per-token + per-IP, /healthz exempt) →
Bearer-auth → circuit-breaker на /mcp (503 при каскадных сбоях движка).
"""

import time

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.core.rate_limiter import CircuitBreaker, SlidingWindowRateLimiter
from src.remote_main import build_app


def _fake_mcp_app() -> Starlette:
    async def _echo(request):
        return JSONResponse({"ok": True})

    return Starlette(routes=[Route("/inner", _echo)])


def _client(token: str, **kwargs) -> TestClient:
    return TestClient(build_app(mcp_app=_fake_mcp_app(), token=token, **kwargs))


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


# ── Rate limit (Фаза 3 шаг 4: SlidingWindowRateLimiter reuse) ──


def test_rate_limit_per_token_first():
    # token-ключ проверяется раньше IP: один и тот же токен исчерпывает
    # свой бюджет → 429 с key=token (IP ещё не исчерпан)
    c = _client("SECRET", rate_limit_rps=1.0)
    assert c.get("/mcp/inner", headers={"Authorization": "Bearer SECRET"}).status_code == 200
    r = c.get("/mcp/inner", headers={"Authorization": "Bearer SECRET"})
    assert r.status_code == 429
    assert r.json()["key"] == "token"
    assert r.headers.get("Retry-After") == "1"


def test_rate_limit_ip_backstop():
    # auth выключен, но лимитер всё равно строит token-ключи из Bearer-заголовка
    c = _client("", rate_limit_rps=1.0)
    assert c.get("/mcp/inner", headers={"Authorization": "Bearer A"}).status_code == 200
    # второй токен с того же IP: token-бюджет свободен, но IP исчерпан
    r = c.get("/mcp/inner", headers={"Authorization": "Bearer B"})
    assert r.status_code == 429
    assert r.json()["key"] == "ip"


def test_rate_limit_healthz_exempt():
    c = _client("SECRET", rate_limit_rps=1.0)
    # исчерпываем лимит на /mcp
    assert c.get("/mcp/inner", headers={"Authorization": "Bearer SECRET"}).status_code == 200
    assert c.get("/mcp/inner", headers={"Authorization": "Bearer SECRET"}).status_code == 429
    # /healthz не лимитируется (uptime-мониторы)
    assert c.get("/healthz").status_code == 200
    assert c.get("/healthz").status_code == 200


def test_rate_limit_disabled_when_rps_non_positive():
    c = _client("", rate_limit_rps=0)
    for _ in range(5):
        assert c.get("/mcp/inner").status_code == 200


def test_rate_limit_tracks_token_hash_not_plaintext():
    limiter = SlidingWindowRateLimiter()
    c = _client("SECRET", rate_limit_rps=100.0, limiter=limiter)
    c.get("/mcp/inner", headers={"Authorization": "Bearer SECRET"})
    keys = list(limiter._windows.keys())
    assert not any("SECRET" in k for k in keys)
    assert any(k.startswith("token:") for k in keys)


# ── Circuit breaker (Фаза 3 шаг 4: CircuitBreaker reuse) ──


def _broken_mcp_app(counter: dict) -> Starlette:
    async def _boom(request):
        counter["calls"] += 1
        raise RuntimeError("engine down")

    return Starlette(routes=[Route("/inner", _boom)])


def test_circuit_breaker_returns_503_and_opens():
    counter = {"calls": 0}
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0, name="test")
    c = TestClient(build_app(mcp_app=_broken_mcp_app(counter), token="", breaker=breaker))
    # до порога движок вызывается, 5xx/exception → 503 (fallback)
    assert c.get("/mcp/inner").status_code == 503
    assert counter["calls"] == 1
    # 2-й промах достигает порога → OPEN
    assert c.get("/mcp/inner").status_code == 503
    assert counter["calls"] == 2
    # OPEN: движок БОЛЬШЕ не вызывается (short-circuit), 503
    assert c.get("/mcp/inner").status_code == 503
    assert counter["calls"] == 2
    assert breaker.get_state()["state"] == "open"
    # /healthz не под circuit breaker
    assert c.get("/healthz").status_code == 200


def test_circuit_breaker_half_open_recovery():
    counter = {"calls": 0}
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1, name="test")
    c = TestClient(build_app(mcp_app=_broken_mcp_app(counter), token="", breaker=breaker))
    assert c.get("/mcp/inner").status_code == 503  # failure → OPEN
    assert c.get("/mcp/inner").status_code == 503  # OPEN bypass
    assert counter["calls"] == 1

    time.sleep(0.12)  # recovery_timeout истёк → HALF_OPEN на следующем запросе

    async def _ok(request):
        counter["calls"] += 1
        return JSONResponse({"ok": True})

    healed = Starlette(routes=[Route("/inner", _ok)])
    c2 = TestClient(build_app(mcp_app=healed, token="", breaker=breaker))
    assert c2.get("/mcp/inner").status_code == 200
    assert counter["calls"] == 2  # пробный запрос дошёл до движка
    assert breaker.get_state()["state"] == "closed"


def test_circuit_breaker_passthrough_when_healthy():
    counter = {"calls": 0}

    async def _echo(request):
        counter["calls"] += 1
        return JSONResponse({"ok": True})

    c = TestClient(build_app(mcp_app=Starlette(routes=[Route("/inner", _echo)]), token=""))
    assert c.get("/mcp/inner").status_code == 200
    assert counter["calls"] == 1
    assert c.get("/healthz").status_code == 200
