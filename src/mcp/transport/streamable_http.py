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
    # remote_main монтирует этот ASGI-апп на /mcp (Mount("/mcp")). FastMCP по
    # умолчанию вешает Streamable-HTTP эндпоинт тоже на /mcp — итоговый путь
    # получался /mcp/mcp, отчего POST /mcp/ отдавал 404. Ставим внутренний
    # путь на корень "/", чтобы после стрипа префикса Mount совпадал ровно /mcp.
    try:
        mcp.settings.streamable_http_path = "/"
        # FastMCP включает DNS-rebinding защиту (проверка заголовка Host),
        # которая по умолчанию отвергает localhost/127.0.0.1 (421). Для
        # локального remote-сервера (bind 127.0.0.1 + Bearer-аутентификация
        # в remote_main) эта проверка избыточна — отключаем, чтобы opencode
        # мог подключаться по http://localhost:8089/mcp.
        sec = mcp.settings.transport_security
        if sec is not None:
            sec.enable_dns_rebinding_protection = False
    except Exception:  # noqa: BLE001 - защита от смены API FastMCP (pragma: no cover)
        pass
    return mcp.streamable_http_app(), mcp.session_manager
