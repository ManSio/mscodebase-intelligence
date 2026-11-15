"""Streamable HTTP транспорт (Фаза 3, ТЗ §3).

Оборачивает существующий MCP-сервер (create_mcp_server, src/mcp/
server_factory.py) в Streamable HTTP ASGI-приложение. Транспорт — не протокол,
а способ запуска того же движка: stdio для локальных клиентов (Zed/VS Code),
Streamable HTTP — для remote (VPS/Docker). Спека MCP 2026: stdio + Streamable
HTTP — единственные стандартные биндинги; HTTP+SSE deprecated (SEP-2596).
"""
from __future__ import annotations


def _transport_security(mcp):
    """DNS-rebinding protection выключена: периметр держит Bearer в remote_main.

    Нужно явное значение на обеих линиях SDK:

    * 1.x — флаг живёт в `mcp.settings.transport_security`;
    * 2.x — поля в `Settings` больше нет, а `streamable_http_app(...)` при
      `transport_security=None` включает защиту с allowlist
      `127.0.0.1 / localhost / [::1]`, из-за чего запрос с `Host: <lan-ip>`
      получает 421 даже при выключенном remote-режиме. Поэтому на 2.x
      передаём `TransportSecuritySettings(enable_dns_rebinding_protection=False)`.

    Возвращаемый объект нужен только ветке 2.x (в 1.x app принимает настройки
    из `settings`, и они мутируются в `_build_streamable_http_app`).
    """
    try:
        from mcp.server.transport_security import TransportSecuritySettings

        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    except Exception:  # noqa: BLE001 - старая линия/иное имя модуля
        pass
    try:
        sec = getattr(getattr(mcp, "settings", None), "transport_security", None)
        if sec is not None:
            sec.enable_dns_rebinding_protection = False
        return sec
    except Exception:  # noqa: BLE001 - не ломаем старт ради настройки
        return None


def _build_streamable_http_app(mcp):
    """ASGI-приложение + session manager для уже созданного сервера.

    Вынесено из `create_streamable_http_app`, чтобы регресс-тесты могли
    строить настоящий app без полного DI-контейнера (`tests/test_streamable_http_host.py`).
    """
    # remote_main монтирует app на /mcp (Mount("/mcp")). SDK по умолчанию вешает
    # эндпоинт тоже на /mcp — итоговый путь получался /mcp/mcp, и POST /mcp/
    # отдавал 404. Внутренний путь = "/", чтобы после стрипа префикса Mount
    # совпадал ровно /mcp. На 2.x это параметр app-метода, на 1.x — settings.
    try:
        return (
            mcp.streamable_http_app(
                streamable_http_path="/",
                transport_security=_transport_security(mcp),
            ),
            mcp.session_manager,
        )
    except TypeError:
        pass

    try:
        mcp.settings.streamable_http_path = "/"
        sec = mcp.settings.transport_security
        if sec is not None:
            sec.enable_dns_rebinding_protection = False
    except Exception:  # noqa: BLE001 - защита от смены API (1.x, pragma: no cover)
        pass
    return mcp.streamable_http_app(), mcp.session_manager


def create_streamable_http_app():
    """Строит MCP-сервер и возвращает его Streamable HTTP ASGI-приложение.

    mcp SDK (`streamable_http_app`) даёт Starlette ASGI app из коробки;
    remote_main монтирует его на /mcp + /healthz + Bearer-auth.
    """
    from src.mcp.server_factory import create_mcp_server

    return _build_streamable_http_app(create_mcp_server())
