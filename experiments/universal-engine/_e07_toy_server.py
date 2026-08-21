"""E-07 toy-сервер — минимальный FastMCP для валидации гарнесса эквивалентности
транспортов БЕЗ тяжёлого движка (не запускает embedder/PID-lock, не трогает
артефакты основного MCP). Запускается по stdio (по умолчанию) или HTTP (--http PORT).

Используется только e07_equiv.py --toy.
"""
from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("e07-toy")


@mcp.tool()
def ping(prefix: str) -> str:
    """Детерминированный эхо-тул: проверяет эквивалентность stdio/HTTP на манер
    «правильный вход → правильный выход» (см. §2.3 / §5.13, не только 0 ошибок)."""
    return f"{prefix}:pong"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, default=0)
    a = ap.parse_args()
    if a.http:
        import uvicorn

        uvicorn.run(mcp.streamable_http_app(), host="127.0.0.1", port=a.http)
    else:
        mcp.run()  # stdio-транспорт по умолчанию


if __name__ == "__main__":
    main()
