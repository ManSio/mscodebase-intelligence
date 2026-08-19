"""mscodebase-cli — тонкий wrapper: вызывает tool-классы движка НАПРЯМУЮ (без MCP).

Для CI/скриптов/админа: тот же DI (create_service_collection), тот же
MCPTool.execute(), но без MCP-протокола. Диспетчер — по имени тула из curated
allowlist (безопасные/детерминированные, минимум внешних зависимостей).

Запуск:
    python -m src.cli <tool> '<json-args>' [--project <root>]
    echo '<json>' | python -m src.cli <tool> -          # аргументы из stdin

Пример:
    python -m src.cli get_task_status '{}'
    python -m src.cli stale_detector '{}' --project D:/Project/Foo
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Type

from src.core.di_container import create_service_collection


def core_tool_allowlist() -> dict:
    """name -> MCPTool class. Curated: детерминированные/админ. Неизвестный -> отказ."""
    from src.mcp.tools.context_tool import GetContextTool
    from src.mcp.tools.doc_tools import StaleDetectorTool
    from src.mcp.tools.graph_tools import GraphQueryTool
    from src.mcp.tools.investigation_tools import FindSimilarBugsTool
    from src.mcp.tools.lifecycle_tools import GetTaskStatusTool

    return {
        "get_task_status": GetTaskStatusTool,
        "stale_detector": StaleDetectorTool,
        "get_context": GetContextTool,
        "graph_query": GraphQueryTool,
        "find_similar_bugs": FindSimilarBugsTool,
    }


def _load_arguments(cli_text: str) -> dict:
    text = cli_text.strip() if cli_text else "{}"
    if text == "-":
        return json.load(sys.stdin)
    return json.loads(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="mscodebase-cli",
        description="MSCodebase tool-call CLI (direct, no MCP).",
    )
    parser.add_argument("tool", help="имя тула из allowlist")
    parser.add_argument("arguments", nargs="?", default="{}",
                        help="JSON-args или '-' для stdin")
    parser.add_argument("--project", default=None, help="project root (default: cwd)")
    args = parser.parse_args(argv)

    allowlist = core_tool_allowlist()
    if args.tool not in allowlist:
        print(json.dumps({
            "error": f"unsupported CLI tool '{args.tool}'",
            "allowed": sorted(allowlist),
        }), file=sys.stderr)
        return 2

    try:
        call_args = _load_arguments(args.arguments)
        if not isinstance(call_args, dict):
            raise ValueError("arguments must be a JSON object")
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"bad arguments: {e}"}), file=sys.stderr)
        return 2

    project_root = Path(args.project).resolve() if args.project else Path(".").resolve()

    services = None
    try:
        services = create_service_collection(project_root)
        cls: Type = allowlist[args.tool]
        instance = cls(services)
        result = instance.execute(**call_args)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        print(json.dumps({"ok": True, "tool": args.tool, "result": result},
                         default=str, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001 — CI-friendly: ошибка тула = exit 1 + json
        print(json.dumps({"ok": False, "tool": args.tool,
                          "error": f"{type(e).__name__}: {e}"}), file=sys.stderr)
        return 1
    finally:
        _safe_shutdown(services)


def _safe_shutdown(services) -> None:
    """Закрывает DI-сервисы (реализующие close/shutdown); не роняет CLI при сбое."""
    if services is None:
        return
    try:
        shutdown = getattr(services, "shutdown", None)
        if shutdown is None:
            return
        res = shutdown()
        if asyncio.iscoroutine(res):
            asyncio.run(res)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    raise SystemExit(main())
