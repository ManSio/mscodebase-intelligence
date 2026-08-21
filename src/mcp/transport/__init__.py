"""Transport Layer (ТЗ §1, §3) — как клиент говорит с движком.

    src/mcp/transport/stdio.py        — stdio (текущий, локальные клиенты)
    src/mcp/transport/streamable_http.py — Streamable HTTP (remote/VPS, Фаза 3)

Требование ТЗ §3: транспорт не завязан на 43 tool-класса — сервер строится
один раз (create_mcp_server), а транспорт выбирается на этапе запуска.
"""
