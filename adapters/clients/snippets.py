"""Ready-to-paste MCP client snippets (G5).

The server is host-neutral: one stdio command plus a few environment variables.
Hosts differ only in the JSON envelope they read, so the envelope is generated
here and `install.py --print-config --client <name>` prints the result.

Envelope shapes are not invented: each one mirrors what the corresponding
adapter/host consumes today.

    generic, claude-code, cursor  -> {"mcpServers": {...}}
    opencode                      -> {"mcp": {name: {"type": "local", ...}}}
    zed                           -> {"context_servers": {name: {command, args,
                                     env, enabled}}}  — same keys that
                                     adapters/zed/zed_config._make_server_entry
                                     writes into settings.json.

Usage:
    from adapters.clients.snippets import render_snippet
    print(render_snippet("generic", command=exe, args=["-u", "-m", "src.main"],
                         env={"PYTHONPATH": root, "PROJECT_PATH": proj}))
"""

from __future__ import annotations

import json
from typing import Mapping, Sequence

__all__ = ["CLIENTS", "SERVER_NAME", "render_snippet", "snapshot"]

SERVER_NAME = "mscodebase"

#: Clients `--print-config` accepts. Order is the order documented in CLIENTS.md.
CLIENTS = ("generic", "opencode", "zed", "claude-code", "cursor")


def snapshot(
    client: str,
    *,
    command: str,
    args: Sequence[str],
    env: Mapping[str, str],
) -> dict:
    """Return the snippet as a dict (the JSON text is just its serialization)."""
    if client not in CLIENTS:
        raise ValueError(f"unknown client {client!r}; known: {', '.join(CLIENTS)}")

    env_dict = dict(env)
    server = {
        "command": command,
        "args": list(args),
        "env": env_dict,
    }

    if client in ("generic", "claude-code", "cursor"):
        return {"mcpServers": {SERVER_NAME: server}}
    if client == "opencode":
        # OpenCode V2: names live under mcp.servers, never directly under mcp.
        # Source: https://opencode.ai/docs/mcp-servers ("V2 does not place server
        # names directly under `mcp`"). The flat `mcp.<name>` layout of V1 is
        # still accepted for migrated configs, but new configs use `servers`.
        return {
            "mcp": {
                "servers": {
                    SERVER_NAME: {
                        "type": "local",
                        "command": [command, *args],
                        "environment": env_dict,
                    }
                }
            }
        }
    # Zed: keys match adapters/zed/zed_config._make_server_entry.
    return {
        "context_servers": {
            SERVER_NAME: {
                "command": command,
                "args": list(args),
                "env": env_dict,
                "enabled": True,
            }
        }
    }


def render_snippet(
    client: str,
    *,
    command: str,
    args: Sequence[str],
    env: Mapping[str, str],
) -> str:
    """Pretty-printed JSON snippet, newline-terminated."""
    payload = snapshot(client, command=command, args=args, env=env)
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
