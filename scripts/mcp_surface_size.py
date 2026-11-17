#!/usr/bin/env python
"""Замер поверхности MCP: сколько инструментов в `tools/list` и сколько это символов.

Число, которое видит клиент, зависит от сериализации, поэтому метод зафиксирован:
`ListToolsResult.model_dump_json()` — ровно то, что уходит по протоколу, со всеми
полями (без `exclude_none`). Запуск:

    python scripts/mcp_surface_size.py

Печатает по одной строке на профиль: `core=<n> chars=<m>` и `full=<n> chars=<m>`.
Числа перевыводятся этим запуском, а не берутся из документации.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def measure(profile: str) -> tuple[int, int]:
    os.environ["MSCODEBASE_MCP_PROFILE"] = profile
    os.environ["MSCODEBASE_DENSE_OFF"] = "true"
    os.environ["LLAMA_CPP_ENABLED"] = "false"

    from src.mcp.server_factory import create_mcp_server

    mcp = create_mcp_server()
    if mcp is None:
        raise RuntimeError("create_mcp_server() returned None")
    items = asyncio.run(mcp.list_tools())
    from mcp.types import ListToolsResult

    payload = ListToolsResult(tools=list(items)).model_dump_json()
    return len(items), len(payload)


def main() -> int:
    for profile in ("core", "full"):
        tools, chars = measure(profile)
        # CLI-вывод через stdout.write: это результат команды, а не отладка,
        # и гейт протокола не должен принимать его за print-мусор.
        sys.stdout.write(f"{profile}={tools} chars={chars}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
