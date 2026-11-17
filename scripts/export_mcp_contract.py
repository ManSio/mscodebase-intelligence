#!/usr/bin/env python
"""Экспорт MCP-контракта: имена, описания, схемы, annotations.

Зачем: у нас 69 инструментов, часть без annotations, и schema drift между
реестром и клиентом ловится только руками. Артефакт детерминирован (sorted,
sha256) и проверяется тестом `tests/test_mcp_contract.py`.

Запуск:
    python scripts/export_mcp_contract.py [--check]

`--check` не пишет файл, а сравнивает с текущим и возвращает rc=1 при дрейфе.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "docs" / "MCP_CONTRACT.json"
SCHEMA = "mscodebase-mcp-contract/v1"


def build_contract() -> dict:
    """Собирает контракт из зарегистрированного реестра (все 69, не профиль)."""
    # Профиль не должен резать реестр во время экспорта.
    # Контракт — это ДЕФОЛТНАЯ сборка: амбиентный env (тесты включают
    # MSCODEBASE_EXECUTE_SCRIPT_ENABLED, allowlist) не должен менять артефакт.
    # Правки env восстанавливаются: иначе вызов из теста оставляет процессу
    # чужой профиль и ломает следующий тест по порядку (ревью 2026-11-17).
    _KEYS = (
        "MSCODEBASE_MCP_PROFILE",
        "MSCODEBASE_EXECUTE_SCRIPT_ENABLED",
        "MSCODEBASE_MCP_TOOLS",
        "MSCODEBASE_DENSE_OFF",
        "LLAMA_CPP_ENABLED",
        # self-indexing guard не должен менять контракт: на CI репозиторий — не
        # «user project», и intel-слой (16 инструментов) не регистрируется.
        "MSCODEBASE_ALLOW_SELF_INDEX",
    )
    saved = {key: os.environ.get(key) for key in _KEYS}
    mcp = None
    try:
        os.environ["MSCODEBASE_MCP_PROFILE"] = "full"
        os.environ["MSCODEBASE_EXECUTE_SCRIPT_ENABLED"] = "false"
        os.environ.pop("MSCODEBASE_MCP_TOOLS", None)
        os.environ["MSCODEBASE_DENSE_OFF"] = "true"
        os.environ["LLAMA_CPP_ENABLED"] = "false"
        os.environ["MSCODEBASE_ALLOW_SELF_INDEX"] = "1"

        from src.mcp.server_factory import create_mcp_server

        mcp = create_mcp_server()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    if mcp is None:
        raise RuntimeError("create_mcp_server() returned None")
    manager = mcp._tool_manager  # noqa: SLF001 — реестр инструментов
    tools = []
    for name, tool in sorted(manager._tools.items()):  # noqa: SLF001
        annotations = getattr(tool, "annotations", None)
        tools.append({
            "name": name,
            "description": (getattr(tool, "description", "") or "").strip(),
            "inputSchema": getattr(tool, "parameters", {}) or {},
            "annotations": annotations.model_dump(mode="json", exclude_none=True)
            if annotations is not None else {},
        })
    encoded = json.dumps(tools, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema": SCHEMA,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "tool_count": len(tools),
        "tools": tools,
    }


def render(contract: dict) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def check_contract(contract: dict) -> int:
    if not ARTIFACT.exists():
        print(f"контракт отсутствует: {ARTIFACT}")
        return 1
    current = ARTIFACT.read_text(encoding="utf-8")
    expected = render(contract)
    if current == expected:
        print(f"MCP_CONTRACT.json: OK ({contract['tool_count']} инструментов)")
        return 0
    print("MCP_CONTRACT.json устарел — перегенерируйте: python scripts/export_mcp_contract.py")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    contract = build_contract()
    if args.check:
        return check_contract(contract)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(render(contract), encoding="utf-8", newline="\n")
    print(f"записано {ARTIFACT} ({contract['tool_count']} инструментов, sha256={contract['sha256'][:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
