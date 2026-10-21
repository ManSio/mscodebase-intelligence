"""MCP wrapper: the whole pipeline as ONE tool for OpenCode.

OpenCode (cloud) calls `pipeline_run` once and gets a receipt list plus a short
summary; it never sees the microsteps, their observations, or the transcripts.

Protocol: MCP over stdio, line-delimited JSON-RPC, stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import Executor, run_task  # noqa: E402

PRISTINE = Path(os.environ.get("MSC_PIPELINE_PRISTINE", "")).resolve() if os.environ.get(
    "MSC_PIPELINE_PRISTINE"
) else None


def respond(msg_id, result: dict) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


def tool_run(args: dict) -> dict:
    task = str(args.get("task", ""))
    repo = Path(str(args.get("repo", "."))).resolve()
    pristine = Path(str(args.get("pristine") or PRISTINE or repo)).resolve()
    test_files = args.get("test_files") or None
    executor = Executor()
    payload = run_task(task, repo, pristine, executor, test_files=test_files)
    return payload


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            respond(
                msg_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "microtask-pipeline", "version": "0.2.0"},
                },
            )
        elif method == "tools/list":
            respond(
                msg_id,
                {
                    "tools": [
                        {
                            "name": "pipeline_run",
                            "description": (
                                "Run a coding task through the microtask pipeline: a code-built plan, "
                                "bounded one-tool microsteps (search / read / write), code "
                                "verification, and machine-checked receipts. Returns the receipts "
                                "and a short summary; the caller does not re-verify."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "task": {"type": "string", "description": "what must be done"},
                                    "repo": {"type": "string", "description": "repo root"},
                                    "pristine": {
                                        "type": "string",
                                        "description": "pristine copy for scope/test-tamper checks",
                                    },
                                    "test_files": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "scope: the test files this task touches",
                                    },
                                },
                                "required": ["task", "repo"],
                            },
                        }
                    ]
                },
            )
        elif method == "tools/call":
            args = (msg.get("params") or {}).get("arguments") or {}
            started = time.monotonic()
            try:
                payload = tool_run(args)
            except Exception as exc:  # noqa: BLE001
                payload = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            payload["wall_s"] = round(time.monotonic() - started, 2)
            respond(
                msg_id,
                {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)[:8000]}],
                    "isError": payload.get("status") == "error",
                },
            )
        elif msg_id is not None:
            respond(msg_id, {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
