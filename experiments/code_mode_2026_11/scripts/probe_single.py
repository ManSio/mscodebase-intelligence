"""Probe one MCP tool call over the real protocol; report chars/tokens of the answer."""
from __future__ import annotations

from pathlib import Path

import contextlib
import json
import os
import subprocess
import sys
import threading
import time

import tiktoken

REPO = str(Path(__file__).resolve().parents[3])  # repo root, no personal path
PY = os.path.join(
    os.environ["LOCALAPPDATA"],
    "Zed", "extensions", "mscodebase-intelligence", "venv", "Scripts", "python.exe",
)
ENC = tiktoken.get_encoding("cl100k_base")
INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
               "clientInfo": {"name": "probe", "version": "0"}},
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
    name, out = sys.argv[1], sys.argv[2]
    # PowerShell mangles inline JSON quoting when calling a native exe, so args
    # always come from a file (argv[3]), never from the command line.
    args = json.load(open(sys.argv[3], encoding="utf-8")) if len(sys.argv) > 3 else {}
    env = os.environ.copy()
    env.update({"PYTHONPATH": REPO, "PROJECT_PATH": REPO, "PYTHONUTF8": "1",
                "LOG_LEVEL": "ERROR", "MSCODEBASE_MCP_PROFILE": "core"})
    err_tail: list[str] = []

    def drain(stream):
        for line in iter(stream.readline, ""):
            err_tail.append(line.rstrip())

    with contextlib.nullcontext(REPO) as cwd:
        proc = subprocess.Popen([PY, "-u", "-m", "src.main"], cwd=cwd, env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace")
        threading.Thread(target=drain, args=(proc.stderr,), daemon=True).start()
        try:
            proc.stdin.write(json.dumps(INITIALIZE) + "\n"); proc.stdin.flush()
            if not read_msg(proc.stdout, 300):
                print("no initialize:", " | ".join(err_tail[-5:])[:600]); return 2
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            t0 = time.time()
            req = {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                   "params": {"name": name, "arguments": args}}
            proc.stdin.write(json.dumps(req) + "\n"); proc.stdin.flush()
            resp = read_msg(proc.stdout, 300)
            dt = round((time.time() - t0) * 1000)
            text = json.dumps(resp, ensure_ascii=False) if resp else ""
            summary = {"call": name, "args": args, "ms": dt,
                       "chars": len(text), "tokens": len(ENC.encode(text))}
            with open(out, "w", encoding="utf-8") as fh:
                json.dump({"summary": summary, "raw": resp}, fh, ensure_ascii=False, indent=1)
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        finally:
            proc.kill()
            proc.wait(timeout=30)


if __name__ == "__main__":
    raise SystemExit(main())
