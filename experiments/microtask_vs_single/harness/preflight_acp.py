"""Pilot gates G1/G4: distinct ACP sessions in one process, then cleanup.

This does not call a model. It starts opencode in an isolated HOME, creates two
sessions, checks that their IDs differ, closes them, and deletes them through
the CLI.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from acp_client import AcpClient, AcpError, find_opencode

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_env(root: Path) -> dict[str, str]:
    home = root / "home"
    home.mkdir(parents=True)
    for name in (".config", ".local/share", ".cache"):
        (home / name).mkdir(parents=True, exist_ok=True)
    config = root / "opencode.json"
    config.write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "model": "opencode/deepseek-v4.1-flash-free",
                "mcp": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(config)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("OPENCODE_SERVER_PASSWORD", None)
    env.pop("OPENCODE_SERVER_USERNAME", None)
    return env


def main() -> int:
    binary = find_opencode()
    if not binary:
        print("ACP PREFLIGHT: SKIP (opencode binary not found)")
        return 2

    with tempfile.TemporaryDirectory(prefix="microtask-acp-") as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        (project / "README.md").write_text("frozen ACP preflight\n", encoding="utf-8")
        env = build_env(root)

        client = AcpClient(binary, project, env)
        ids: list[str] = []
        try:
            init = client.start()
            print(f"INIT: agent={init.get('agentInfo', {}).get('name')!r} protocol={init.get('protocolVersion')!r}")
            for _ in range(2):
                result = client.new_session(project)
                sid = result.get("sessionId")
                if not sid:
                    print(f"ACP PREFLIGHT: FAIL (no sessionId: {result})")
                    return 1
                ids.append(sid)
            print(f"SESSIONS: {ids}")
            if len(set(ids)) != 2:
                print("ACP PREFLIGHT: FAIL (session IDs are not distinct)")
                return 1
            for sid in ids:
                client.close_session(sid)
            print("CLOSE: OK")
        except AcpError as exc:
            print(f"ACP PREFLIGHT: FAIL ({exc})")
            return 1
        finally:
            client.stop()

        deleted = []
        for sid in ids:
            proc = client.delete_session_cli(sid)
            if proc.returncode != 0:
                print(f"DELETE FAIL {sid}: rc={proc.returncode} {proc.stderr[-500:]}")
                return 1
            deleted.append(sid)
        print(f"DELETE: OK ({len(deleted)})")

    print("ACP PREFLIGHT: PASS (2 distinct sessions, close, delete)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

