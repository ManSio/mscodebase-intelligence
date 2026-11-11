"""Cold-start check for the client snippets printed by `install.py --print-config`.

For every client it renders the snippet exactly as the installer does, launches
the command from it in a throwaway directory, performs an MCP `initialize`
handshake and then `tools/list`, and reports PASS/FAIL per client. This is the
mechanical proof behind the copy-paste sections of docs/CLIENTS.md: the snippet
is not just valid JSON, it starts a server that answers.

Usage:
    python scripts/verify_client_snippets.py [--python PATH] [--timeout SEC]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# ENCODING SAFETY (Windows): the server's stderr tail is Russian, and a cp1252
# console crashes the report with UnicodeEncodeError (windows-latest, 2026-11-12).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from adapters.clients.snippets import CLIENTS, snapshot  # noqa: E402

_TOP_LEVEL = {
    "generic": "mcpServers",
    "claude-code": "mcpServers",
    "cursor": "mcpServers",
    "opencode": "mcp",
    "zed": "context_servers",
}

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "snippet-smoke", "version": "0"},
    },
}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def _entry(client: str, command: str, args: list[str], env: dict[str, str]) -> tuple[str, list[str], dict[str, str]]:
    payload = snapshot(client, command=command, args=args, env=env)[_TOP_LEVEL[client]]["mscodebase"]
    if client == "opencode":
        return payload["command"][0], payload["command"][1:], payload["environment"]
    return payload["command"], payload["args"], payload["env"]


def _read_message(stream, timeout: float):
    """Next JSON object from stdout, or None on timeout/EOF."""
    import queue
    import threading

    box: queue.Queue = queue.Queue(maxsize=1)

    def _worker():
        while True:
            line = stream.readline()
            if not line:
                box.put(None)
                return
            line = line.strip()
            if line.startswith("{"):
                try:
                    box.put(json.loads(line))
                    return
                except json.JSONDecodeError:
                    continue

    threading.Thread(target=_worker, daemon=True).start()
    try:
        return box.get(timeout=timeout)
    except queue.Empty:
        return None


def _probe(client: str, command: str, args: list[str], env: dict[str, str], timeout: int) -> str:
    exe, cli_args, cli_env = _entry(client, command, args, env)
    full_env = os.environ.copy()
    full_env.update(cli_env)
    with tempfile.TemporaryDirectory(prefix="mcp-snippet-", ignore_cleanup_errors=True) as cwd:
        proc = subprocess.Popen(
            [exe, *cli_args],
            cwd=cwd,
            env=full_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            proc.stdin.write(json.dumps(INITIALIZE) + "\n")
            proc.stdin.flush()
            init = _read_message(proc.stdout, timeout)
            if not init or "result" not in init:
                tail = (proc.stderr.readline() if proc.stderr else "") or ""
                return f"FAIL: no initialize result ({tail.strip()})"

            proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            )
            proc.stdin.write(json.dumps(LIST_TOOLS) + "\n")
            proc.stdin.flush()
            listing = _read_message(proc.stdout, timeout)
            tools = len(listing.get("result", {}).get("tools", [])) if listing else 0
            name = init["result"].get("serverInfo", {}).get("name", "?")
            return f"PASS: server={name} tools={tools}"
        finally:
            try:
                proc.kill()
            except OSError:
                pass
            proc.wait(timeout=30)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default="", help="interpreter/entry point to probe (default: current)")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--install-root", default=os.environ.get("MSCODEBASE_INSTALL_ROOT", str(REPO)))
    args = ap.parse_args()

    command = args.python or sys.executable
    env = {"PYTHONPATH": args.install_root, "PROJECT_PATH": tempfile.gettempdir(), "PYTHONUTF8": "1"}

    failures = 0
    for client in CLIENTS:
        result = _probe(client, command, ["-u", "-m", "src.main"], env, args.timeout)
        failures += 0 if result.startswith("PASS") else 1
        print(f"{client:<12} {result}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
