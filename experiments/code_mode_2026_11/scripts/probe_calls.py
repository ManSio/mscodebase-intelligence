"""Probe: run a 3-call chain over real MCP protocol and save raw outputs.

Chain: search_code -> get_symbol_info -> impact_analysis for one symbol.
Measures what the *client* would feed back into the model's context
(arm A: full tool results, one model turn per call).
"""
from __future__ import annotations

from pathlib import Path

import contextlib
import json
import os
import subprocess
import sys
import tempfile
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
CALLS = [
    ("search_code", {"query": "modification_guard", "mode": "fast"}),
    ("get_symbol_info", {"query": "modification_guard"}),
    ("impact_analysis", {"symbol": "modification_guard"}),
]


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
    out = sys.argv[1]
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": REPO, "PROJECT_PATH": REPO, "PYTHONUTF8": "1",
        "LOG_LEVEL": "ERROR", "MSCODEBASE_MCP_PROFILE": "core",
    })
    err_tail: list[str] = []

    def drain(stream):
        for line in iter(stream.readline, ""):
            err_tail.append(line.rstrip())

    results = []
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
            for i, (name, args) in enumerate(CALLS, start=10):
                t0 = time.time()
                req = {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}
                proc.stdin.write(json.dumps(req) + "\n"); proc.stdin.flush()
                resp = read_msg(proc.stdout, 300)
                dt = (time.time() - t0) * 1000
                text = json.dumps(resp, ensure_ascii=False) if resp else ""
                results.append({"call": name, "args": args, "ms": round(dt),
                                "chars": len(text), "tokens": len(ENC.encode(text)),
                                "raw": resp})
            # count the whole conversation payload each of the 3 turns would carry
            running = 0
            cumulative = []
            for r in results:
                running += r["tokens"]
                cumulative.append(running)
            summary = {
                "calls": [{k: r[k] for k in ("call", "ms", "chars", "tokens")} for r in results],
                "total_tokens_naive_sum": running,
                "cumulative_context_tokens": cumulative,
            }
            with open(out, "w", encoding="utf-8") as fh:
                json.dump({"summary": summary, "raw": results}, fh, ensure_ascii=False, indent=1)
            print(json.dumps(summary, indent=1))
            return 0
        finally:
            proc.kill()
            proc.wait(timeout=30)


if __name__ == "__main__":
    raise SystemExit(main())

