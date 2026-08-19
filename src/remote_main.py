"""remote_main.py — вход remote-режима (Фаза 3, ТЗ §3).

Запускает тот же движок по Streamable HTTP для удалённых MCP-клиентов
(Claude Code / VS Code / Zed remote). FastMCP.streamable_http_app монтируется
на /mcp; /healthz для внешнего мониторинга (uptime/systemd); Bearer-auth
(env MSCODEBASE_REMOTE_TOKEN) — обязательна для remote (stdio auth не нужен:
доверенный локальный процесс).

Запуск:
    MSCODEBASE_REMOTE_TOKEN=<token> uvicorn src.remote_main:app --host 0.0.0.0 --port 8089
    # или
    python -m src.remote_main [--host 0.0.0.0] [--port 8089]
"""
from __future__ import annotations

import argparse
import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

SERVICE = "mscodebase-remote"


def _build_mcp_app():
    from src.mcp.transport.streamable_http import create_streamable_http_app

    return create_streamable_http_app()


async def _healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": SERVICE})


class _AuthMiddleware(BaseHTTPMiddleware):  # noqa: BLE001-наследуется от starlette
    """Bearer-auth: req-request кроме /healthz обязан нести Authorization: Bearer <token>."""

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


def build_app(mcp_app=None, token: str | None = None) -> Starlette:
    """Собирает Starlette-приложение: /mcp (Streamable HTTP) + /healthz + auth.

    mcp_app — тестируемая инъекция; None → реальный create_streamable_http_app().
    token None → из env MSCODEBASE_REMOTE_TOKEN.
    """
    if mcp_app is None:
        mcp_app = _build_mcp_app()
    token = token if token is not None else os.environ.get("MSCODEBASE_REMOTE_TOKEN", "").strip()
    middleware = [Middleware(_AuthMiddleware, token=token)] if token else []
    return Starlette(
        middleware=middleware,
        routes=[
            Mount("/mcp", app=mcp_app),
            Route("/healthz", _healthz),
        ],
    )


app = build_app()


# Lazy app: импорт remote_main НЕ должен строить тяжёлый сервер (create_mcp_server).
# uvicorn src.remote_main:app обращается к атрибуту → сборка в момент первого доступа.
APP_ATTR = {"built": False}


def __getattr__(name: str):
    if name == "app" and not APP_ATTR["built"]:
        _app = build_app()
        APP_ATTR["built"] = True
        globals()["app"] = _app
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MSCodeBase remote (Streamable HTTP)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8089)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
