"""Probe: dump MCP tools/list for a given profile (real protocol, real server).

Usage: python probe_tools.py <core|full> <out.json>
"""
from __future__ import annotations

from pathlib import Path

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

REPO = str(Path(__file__).resolve().parents[3])  # repo root, no personal path
PY = os.path.join(
    os.environ["LOCALAPPDATA"],
    "Zed", "extensions", "mscodebase-intelligence", "venv", "Scripts", "python.exe",
)

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "probe", "version": "0"},
    },
}


def read_msg(stream, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def main() -> int:
    profile, out = sys.argv[1], sys.argv[2]
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": REPO,
        "PROJECT_PATH": tempfile.gettempdir(),
        "PYTHONUTF8": "1",
        "LOG_LEVEL": "ERROR",
        "MSCODEBASE_MCP_PROFILE": profile,
    })
    err_tail: list[str] = []

    def drain(stream):
        for line in iter(stream.readline, ""):
            err_tail.append(line.rstrip())

    with tempfile.TemporaryDirectory(prefix="probe-cwd-", ignore_cleanup_errors=True) as cwd:
        proc = subprocess.Popen(
            [PY, "-u", "-m", "src.main"],
            cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        threading.Thread(target=drain, args=(proc.stderr,), daemon=True).start()
        try:
            proc.stdin.write(json.dumps(INITIALIZE) + "\n")
            proc.stdin.flush()
            if not read_msg(proc.stdout, 300):
                print("no initialize result:", " | ".join(err_tail[-5:])[:800])
                return 2
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
            proc.stdin.flush()
            listing = read_msg(proc.stdout, 300)
            if not listing or "result" not in listing:
                print("no tools/list result:", " | ".join(err_tail[-5:])[:800])
                return 3
            tools = listing["result"]["tools"]
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(tools, fh, ensure_ascii=False, indent=1)
            print(f"{profile}: {len(tools)} tools -> {out}")
            return 0
        finally:
            proc.kill()
            proc.wait(timeout=30)


if __name__ == "__main__":
    raise SystemExit(main())
