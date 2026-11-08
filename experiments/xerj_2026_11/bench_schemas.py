"""H6: bytes of JSON schemas the default profile puts in the agent's context.

Baseline for comparison: XERJ publishes 62 373 B for 24 tools (2 598 B/tool).
"""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import os

os.environ.setdefault("MSCODEBASE_MCP_PROFILE", "core")

from src.mcp.server_factory import create_mcp_server  # noqa: E402


async def main() -> int:
    server = create_mcp_server()
    tools = await server.list_tools()
    payload = [t.model_dump() if hasattr(t, "model_dump") else dict(t) for t in tools]
    dumped = json.dumps(payload, ensure_ascii=False)
    size = len(dumped.encode("utf-8"))
    print(f"tools={len(tools)} bytes={size} avg={size // max(1, len(tools))}")
    biggest = sorted(
        ((len(json.dumps(t, ensure_ascii=False).encode("utf-8")), t.get("name", "?"))
         for t in payload),
        reverse=True,
    )[:5]
    for b, name in biggest:
        print(f"  {b:>6} B  {name}")
    return 0


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.stdout.flush()
    # The MCP factory leaves heartbeat/logging threads; their teardown decides
    # the process exit code and would report 1 for a successful measurement.
    os._exit(code)
