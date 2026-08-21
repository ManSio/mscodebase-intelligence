"""Streamable HTTP транспорт (Фаза 3, ТЗ §3).

Оборачивает существующий FastMCP-сервер (create_mcp_server, src/mcp/
server_factory.py) в Streamable HTTP ASGI-приложение. Транспорт — не протокол,
а способ запуска того же движка: stdio для локальных клиентов (Zed/VS Code),
Streamable HTTP — для remote (VPS/Docker). Спека MCP 2026: stdio + Streamable
HTTP — единственные стандартные биндинги; HTTP+SSE deprecated (SEP-2596).
"""
from __future__ import annotations


def create_streamable_http_app():
    """Строит FastMCP-сервер и возвращает его Streamable HTTP ASGI-приложение.

    mcp SDK (FastMCP.streamable_http_app) даёт Starlette ASGI app из коробки;
    remote_main монтирует его на /mcp + /healthz + Bearer-auth.
    """
    from src.mcp.server_factory import create_mcp_server

    mcp = create_mcp_server()
    return mcp.streamable_http_app()
