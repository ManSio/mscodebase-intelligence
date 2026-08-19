"""remote_main.py — вход remote-режима (Фаза 3, ТЗ §3).

Запускает тот же движок по Streamable HTTP для удалённых MCP-клиентов
(Claude Code / VS Code / Zed remote). FastMCP.streamable_http_app монтируется
на /mcp; /healthz для внешнего мониторинга (uptime/systemd); Bearer-auth
(env MSCODEBASE_REMOTE_TOKEN) — обязательна для remote (stdio auth не нужен:
доверенный локальный процесс).

Rate-limit (Фаза 3 шаг 4): переиспользует SlidingWindowRateLimiter +
CircuitBreaker из src/core/rate_limiter.py (threading.Lock — loop-agnostic,
WISDOM: asyncio.Lock дедлочит cross-loop). Слои гейта, снаружи внутрь:
1. per-token + per-IP sliding-window (env MSCODEBASE_REMOTE_RATE_LIMIT_RPS,
   default 30.0 на ключ/сек; 0/negative = выключено; /healthz освобождён);
2. Bearer-auth;
3. CircuitBreaker на /mcp — каскадные сбои движка → быстрый 503, не hang.

Запуск:
    MSCODEBASE_REMOTE_TOKEN=<token> uvicorn src.remote_main:app --host 0.0.0.0 --port 8089
    # или
    python -m src.remote_main [--host 0.0.0.0] [--port 8089]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from src.core.rate_limiter import CircuitBreaker, SlidingWindowRateLimiter

if TYPE_CHECKING:
    app: Starlette  # ленивый module-attr через __getattr__ (PEP 562) — см. ниже

SERVICE = "mscodebase-remote"
_DEFAULT_RPS = 30.0
logger = logging.getLogger("mscodebase_server.remote_main")

# Sentinel для CircuitBreaker.call (fallback): возвращается, когда движок НЕ
# ответил 2xx/4xx (5xx/exception) или при OPEN-short-circuit. Отличается от
# успешного результата _run (True), чтобы решить — слать ли 503.
_OPEN_FALLBACK = object()


class _EngineFailure(Exception):
    """Маркер: движок собрался отправить 5xx — прерываем до клиента.

    Нужен, чтобы HЕ допустить double-send: внутренний ServerErrorMiddleware по
    exception отправляет свой 500, а circuit breaker — свой 503. Перехватываем
    response.start(5xx) и не пускаем его дальше; 503 — единственный ответ.
    """


def _build_mcp_app():
    from src.mcp.transport.streamable_http import create_streamable_http_app

    return create_streamable_http_app()


async def _send_json(send, status: int, body: dict, extra_headers=()):
    headers = [(b"content-type", b"application/json")]
    headers += [(k.encode("utf-8"), v.encode("utf-8")) for k, v in extra_headers]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": json.dumps(body).encode("utf-8")})


async def _healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": SERVICE})


class _AuthMiddleware(BaseHTTPMiddleware):
    """Bearer-auth: любой запрос кроме /healthz обязан нести Authorization: Bearer <token>."""

    def __init__(self, app, token: str):
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        if not self._token:
            return await call_next(request)  # пустой токен = auth выключен
        authz = request.headers.get("Authorization", "")
        if authz != f"Bearer {self._token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def _rate_limited(kind: str) -> JSONResponse:
    logger.warning(f"Remote gate: rate limit exceeded (key='{kind}')")
    return JSONResponse(
        {"error": "rate_limited", "key": kind, "retry_after_seconds": 1},
        status_code=429,
        headers={"Retry-After": "1"},
    )


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-token + per-IP sliding-window rate limit на remote-гейте.

    Переиспользует SlidingWindowRateLimiter (threading.Lock, loop-agnostic —
    WISDOM: asyncio.Lock дедлочит cross-loop). /healthz освобождён: uptime-
    мониторы не должны триппить лимиты и сами не являются поверхностью атаки.

    Порядок проверок: token раньше IP — идентификация вызывающего первична,
    IP — backstop для анонимного/флуд-трафика (например, флуд 401). Токен в
    ключах хранится ТОЛЬКО как sha256 (не plaintext). X-Forwarded-For НЕ
    доверяем (спуфинг обхода лимита) — ключ IP из request.client.host (адрес
    сокета); за reverse-proxy это адрес прокси, реальные IP — только при
    доверенном прокси, вне v1.
    """

    def __init__(
        self,
        app,
        limiter: SlidingWindowRateLimiter | None = None,
        rps: float = _DEFAULT_RPS,
    ):
        super().__init__(app)
        self._limiter = limiter or SlidingWindowRateLimiter()
        self._rps = rps

    @staticmethod
    def _token_key(request: Request) -> str | None:
        authz = request.headers.get("Authorization", "")
        if not authz.startswith("Bearer "):
            return None
        token = authz[len("Bearer "):].strip()
        if not token:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return f"token:{digest}"

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        token_key = self._token_key(request)
        if token_key and not self._limiter.acquire(token_key, self._rps):
            return _rate_limited("token")
        host = request.client.host if request.client else "unknown"
        if not self._limiter.acquire(f"ip:{host}", self._rps):
            return _rate_limited("ip")
        return await call_next(request)


class _CircuitBreakerMount:
    """ASGI-обёртка mount /mcp: circuit breaker + exception→503 (Фаза 3 шаг 4).

    BaseHTTPMiddleware для этого не годится: исключения вложенного Mount
    всплывают после dispatch (Starlette streaming-модель) и ловятся поздно.
    Здесь оборачиваем ASGI-вызов напрямую и переиспользуем CircuitBreaker.call:
    - 5xx/exception → failure_count++, OPEN → быстрый 503 без вызова движка;
    - HALF_OPEN → пробный запрос; успех → CLOSED (реюз state-mach-ины).
    try/except вокруг breaker.call не нужен: fallback non-None → call() не рейзит.
    """

    def __init__(self, mcp_app, breaker: CircuitBreaker | None = None):
        self.mcp_app = mcp_app
        self._breaker = breaker or CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            name="remote-mcp",
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.mcp_app(scope, receive, send)

        responded = False

        async def _wrapped_send(message):
            nonlocal responded
            if message["type"] == "http.response.start":
                if message["status"] >= 500:
                    # 5xx движка: не пускаем 500 до клиента — breaker ответит
                    # единственным 503 (позволяет избежать double-send 500+503).
                    raise _EngineFailure()
                responded = True
            await send(message)

        async def _run():
            await self.mcp_app(scope, receive, _wrapped_send)
            return True

        result = await self._breaker.call(_run, fallback=_OPEN_FALLBACK)
        if result is _OPEN_FALLBACK and not responded:
            logger.warning("Remote gate: circuit OPEN/5xx for /mcp (503 fallback)")
            await _send_json(
                send,
                503,
                {"error": "circuit_open", "service": SERVICE},
                extra_headers=[("Retry-After", "30")],
            )


def build_app(
    mcp_app=None,
    token: str | None = None,
    *,
    rate_limit_rps: float | None = None,
    limiter: SlidingWindowRateLimiter | None = None,
    breaker: CircuitBreaker | None = None,
) -> Starlette:
    """Собирает Starlette-приложение: /mcp (Streamable HTTP) + /healthz + гейт.

    mcp_app — тестируемая инъекция; None → реальный create_streamable_http_app().
    token None → из env MSCODEBASE_REMOTE_TOKEN.
    rate_limit_rps None → из env MSCODEBASE_REMOTE_RATE_LIMIT_RPS
        (default 30.0 на ключ/сек); <= 0 → rate-limit middleware не добавляется.
    limiter/breaker — тестируемые инъекции (None → свежие экземпляры).
    Порядок гейта (снаружи внутрь): rate-limit → auth → circuit-breaker (на /mcp).
    """
    if mcp_app is None:
        mcp_app = _build_mcp_app()
    token = token if token is not None else os.environ.get("MSCODEBASE_REMOTE_TOKEN", "").strip()

    if rate_limit_rps is None:
        raw = os.environ.get("MSCODEBASE_REMOTE_RATE_LIMIT_RPS", "").strip()
        rate_limit_rps = float(raw) if raw else _DEFAULT_RPS

    middleware: list = []
    if rate_limit_rps > 0:
        middleware.append(Middleware(_RateLimitMiddleware, limiter=limiter, rps=rate_limit_rps))
    if token:
        middleware.append(Middleware(_AuthMiddleware, token=token))
    return Starlette(
        middleware=middleware,
        routes=[
            Mount("/mcp", app=_CircuitBreakerMount(mcp_app, breaker)),
            Route("/healthz", _healthz),
        ],
    )


# Lazy app: импорт remote_main НЕ строит тяжёлый сервер (create_mcp_server).
# uvicorn src.remote_main:app / python -m src.remote_main обращаются к атрибуту
# app → сборка при первом доступе (PEP 562 __getattr__). Ранее `app = build_app()`
# выполнялся жадно на импорте (механизм ленивости был мёртвым кодом) — тесты
# тащили реальный сервер. Теперь импорт лёгкий.
_APP_STATE = {"built": False}


def __getattr__(name: str):
    if name == "app" and not _APP_STATE["built"]:
        _app = build_app()
        _APP_STATE["built"] = True
        globals()["app"] = _app
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MSCodeBase remote (Streamable HTTP)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8089)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)  # noqa: F821 — ленивый module-attr (__getattr__)


if __name__ == "__main__":
    main()
