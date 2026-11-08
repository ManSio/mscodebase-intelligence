"""Minimal ACP client for the experiment harness.

Supports what the pilot needs and nothing more:
- process/session lifecycle (initialize, session/new, session/close, delete);
- session/prompt with notification collection (agent text + tool calls);
- automatic answers to permission requests.

No secret handling: the client never reads credentials. Authentication is the
caller's business (isolated config + proxy).
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def find_opencode() -> str | None:
    explicit = os.environ.get("OPENCODE_BIN")
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("opencode")
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    candidates = []
    if appdata:
        candidates.append(Path(appdata) / "npm" / "opencode.cmd")
    candidates.append(Path.home() / ".opencode" / "bin" / "opencode.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _command(binary: str, args: list[str]) -> list[str]:
    if os.name == "nt" and Path(binary).suffix.lower() in {".cmd", ".bat"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", binary, *args]
    return [binary, *args]


class AcpError(RuntimeError):
    pass


class AcpClient:
    def __init__(self, binary: str, cwd: Path, env: dict[str, str] | None = None) -> None:
        self.binary = binary
        self.cwd = Path(cwd)
        self.env = env or os.environ.copy()
        self.proc: subprocess.Popen | None = None
        self._responses: queue.Queue[dict] = queue.Queue()
        self._updates: list[dict] = []
        self._lock = threading.Lock()
        self._stderr: list[str] = []
        self._reader: threading.Thread | None = None
        self._err_reader: threading.Thread | None = None
        self._next_id = 1
        self.permission_log: list[dict] = []

    # ---------- process ----------

    def start(self, timeout: float = 60.0) -> dict:
        if self.proc is not None:
            raise AcpError("already started")
        self.proc = subprocess.Popen(
            _command(self.binary, ["acp", "--cwd", str(self.cwd)]),
            cwd=str(self.cwd),
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._err_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._err_reader.start()
        return self.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
                "clientInfo": {"name": "microtask-harness", "version": "0.1.0"},
            },
            timeout=timeout,
        )

    def _read_stdout(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                with self._lock:
                    self._updates.append({"method": "_malformed", "raw": line[:400]})
                continue
            if "method" in msg and "id" in msg:
                self._handle_agent_request(msg)
            elif "method" in msg:
                with self._lock:
                    self._updates.append(msg)
            else:
                self._responses.put(msg)

    def _read_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())

    def _handle_agent_request(self, msg: dict) -> None:
        method = msg.get("method")
        if method == "session/request_permission":
            params = msg.get("params") or {}
            options = params.get("options") or []
            chosen = None
            for opt in options:
                if str(opt.get("kind", "")).startswith("allow"):
                    chosen = opt
                    break
            if chosen is None and options:
                chosen = options[0]
            option_id = (chosen or {}).get("optionId")
            with self._lock:
                self.permission_log.append(
                    {
                        "tool": (params.get("toolCall") or {}).get("title"),
                        "options": [o.get("optionId") for o in options],
                        "chosen": option_id,
                    }
                )
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": {"outcome": {"outcome": "selected", "optionId": option_id}},
                }
            )
            return
        # Unknown client-side method: refuse explicitly instead of hanging the agent.
        self._send(
            {
                "jsonrpc": "2.0",
                "id": msg["id"],
                "error": {"code": -32601, "message": f"unsupported client method: {method}"},
            }
        )

    def _send(self, obj: dict) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise AcpError("process is not running")
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    # ---------- protocol ----------

    def request(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        rid = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AcpError(f"timeout waiting for {method}; stderr={self.stderr_tail()}")
            try:
                msg = self._responses.get(timeout=remaining)
            except queue.Empty:
                continue
            if msg.get("id") != rid:
                continue
            if "error" in msg:
                raise AcpError(f"{method} failed: {msg['error']}")
            result = msg.get("result")
            if not isinstance(result, dict):
                raise AcpError(f"{method}: result is not an object: {msg}")
            return result

    def new_session(self, cwd: Path | None = None, timeout: float = 60.0) -> dict:
        return self.request(
            "session/new",
            {"cwd": str(cwd or self.cwd), "mcpServers": []},
            timeout=timeout,
        )

    def prompt(self, session_id: str, text: str, timeout: float = 600.0) -> dict:
        """Send one prompt and return the agent's answer plus the update stream."""
        before = self.update_count()
        result = self.request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
            timeout=timeout,
        )
        with self._lock:
            updates = list(self._updates[before:])
        return {
            "result": result,
            "updates": updates,
            "text": self._agent_text(updates),
            "tool_calls": self._tool_calls(updates),
        }

    def update_count(self) -> int:
        with self._lock:
            return len(self._updates)

    @staticmethod
    def _agent_text(updates: list[dict]) -> str:
        chunks: list[str] = []
        for update in updates:
            params = update.get("params") or {}
            body = params.get("update") or {}
            if body.get("sessionUpdate") == "agent_message_chunk":
                content = body.get("content") or {}
                if content.get("type") == "text" and content.get("text"):
                    chunks.append(content["text"])
        return "".join(chunks)

    @staticmethod
    def _tool_calls(updates: list[dict]) -> list[dict]:
        calls: list[dict] = []
        for update in updates:
            params = update.get("params") or {}
            body = params.get("update") or {}
            kind = body.get("sessionUpdate")
            if kind in {"tool_call", "tool_call_update"}:
                calls.append(
                    {
                        "id": body.get("toolCallId"),
                        "title": body.get("title"),
                        "kind": body.get("kind"),
                        "status": body.get("status"),
                    }
                )
        return calls

    def cancel(self, session_id: str) -> None:
        """Cancel an in-flight prompt (ACP `session/cancel` notification)."""
        self._send(
            {
                "jsonrpc": "2.0",
                "id": f"cancel-{self._next_id}",
                "method": "session/cancel",
                "params": {"sessionId": session_id},
            }
        )

    def tool_call_count(self) -> int:
        """Distinct tool calls seen so far (status updates share one id)."""
        ids: set[str] = set()
        with self._lock:
            for u in self._updates:
                body = (u.get("params") or {}).get("update") or {}
                if body.get("sessionUpdate") in {"tool_call", "tool_call_update"}:
                    call_id = body.get("toolCallId")
                    if call_id:
                        ids.add(call_id)
        return len(ids)

    def close_session(self, session_id: str, timeout: float = 30.0) -> dict:
        return self.request("session/close", {"sessionId": session_id}, timeout=timeout)

    def delete_session_cli(self, session_id: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            _command(self.binary, ["session", "delete", session_id]),
            cwd=str(self.cwd),
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def stderr_tail(self, limit: int = 2000) -> str:
        return "\n".join(self._stderr[-30:])[-limit:]

    def stop(self, timeout: float = 15.0) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        if self._reader:
            self._reader.join(timeout=2)
        if self._err_reader:
            self._err_reader.join(timeout=2)
        self.proc = None

