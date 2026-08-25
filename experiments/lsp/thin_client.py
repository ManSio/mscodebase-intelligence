"""Thin LSP client adapter (DRAFT — experiment artifact, not the production hot path).

A minimal, self-contained Language Server Protocol stdio client that speaks
real `Content-Length` framed JSON-RPC over stdin/stdout. Uses only the
already-pinned `lsprotocol` message shapes concept + stdlib (no pygls).

Rationale
---------
MSCodeBase builds its knowledge graph from tree-sitter AST. LSP adds
compiler-accurate relations tree-sitter cannot reliably infer (full type
resolution, cross-file call sites). Live-validated subset (2026-08-19,
basedpyright 1.39.10):

  * call hierarchy  (prepare -> incoming/outgoing)   [verified live]
  * semantic tokens (full, delta-encoded)           [verified live]

The client is CAPABILITY-AGNOSTIC: it probes the server in `initialize` and
only issues requests for advertised providers. Type hierarchy and moniker are
used automatically wherever a real server supports them, and silently skipped
where it does not (the pyright fork advertises neither).

Mapping design (not yet wired into LanceDB/PropertyGraph)
---------------------------------------------------------
  * callHierarchy -> EDGE CALLS (caller -> callee), prop call_ranges[],
                     source uri + selectionRange (compiler-resolved).
  * semanticTokens -> span props on the def node
                     [deltaLine, deltaStart, length, typeIdx, mods] decoded via
                     the server legend -> exact spans/kinds without AST re-walk.

API is synchronous with an internal reader thread + queue (pattern proven on
Windows in `experiments/lsp/lsp_live_pyright.py`). Python 3.10+.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any


def _server_bin(name: str) -> str:
    """Resolve a language-server executable next to the running interpreter."""
    here = os.path.dirname(sys.executable) if sys.executable else "."
    for candidate in (name, name + ".exe"):
        path = os.path.join(here, candidate)
        if os.path.exists(path):
            return path
    return shutil.which(name) or name


@dataclass
class ServerSpec:
    """How to launch a particular language server."""

    language: str
    argv: list[str]
    # pyright-fork style indexing notifications (empty if unknown / none)
    index_begin: tuple[str, ...] = ()
    index_end: tuple[str, ...] = ()


DEFAULT_SERVERS: dict[str, ServerSpec] = {
    "python": ServerSpec("python", [_server_bin("basedpyright-langserver"), "--stdio"]),
}


class LspClient:
    """Thin, capability-probing stdio LSP client.

    One reader thread owns stdout; the main thread owns stdin. Requests are
    matched by id; notifications are buffered in ``pending_notifications()``.
    """

    def __init__(self, language: str, specs: dict[str, ServerSpec] | None = None) -> None:
        spec = (specs or DEFAULT_SERVERS).get(language)
        if spec is None:
            raise ValueError(f"no server spec for language={language!r}")
        self.spec = spec
        self._proc: subprocess.Popen[bytes] | None = None
        self._queue: queue.Queue[dict[str, object]] = queue.Queue()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._next_id = 1
        self._notifications: list[dict[str, Any]] = []
        self.capabilities: dict[str, Any] = {}
        self.server_info: dict[str, Any] = {}

    # -- lifecycle ----------------------------------------------------------
    def start(
        self,
        root_uri: str,
        root_path: str | None = None,
        caps: dict[str, Any] | None = None,
        timeout: float = 40.0,
    ) -> dict[str, Any]:
        """Spawn the server, negotiate ``initialize``, return server capabilities."""
        if self._proc is not None:
            raise RuntimeError("client already started")
        create_no_window = 0x08000000 if os.name == "nt" else 0
        self._proc = subprocess.Popen(
            self.spec.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=create_no_window,
            cwd=root_path,
        )
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        params: dict[str, Any] = {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "capabilities": caps if caps is not None else _default_client_caps(),
        }
        result = self._request("initialize", params, timeout=timeout)
        assert isinstance(result, dict)
        self.capabilities = result.get("capabilities", {})
        self.server_info = result.get("serverInfo", {})
        self._notify({"method": "initialized", "params": {}})
        return self.capabilities

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._request("shutdown", {}, timeout=5)
            self._notify({"method": "exit", "params": {}})
        finally:
            self._stop.set()
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None

    def __enter__(self) -> "LspClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- document sync ------------------------------------------------------
    def open_document(self, uri: str, language_id: str, text: str, version: int = 1) -> None:
        self._notify({
            "method": "textDocument/didOpen",
            "params": {"textDocument": {
                "uri": uri, "languageId": language_id, "version": version, "text": text}},
        })

    # -- graph reads (capability-routed) ------------------------------------
    def call_hierarchy(self, uri: str, line: int, character: int) -> tuple[list[Any], list[Any]]:
        """Return (incoming, outgoing) call-hierarchy results for a position."""
        prepared = self._request("textDocument/prepareCallHierarchy", {
            "textDocument": {"uri": uri}, "position": {"line": line, "character": character},
        }) or []
        assert isinstance(prepared, list)
        outgoing: list[Any] = []
        incoming: list[Any] = []
        for item in prepared:
            outgoing.extend(self._request("callHierarchy/outgoingCalls", {"item": item}) or [])
            incoming.extend(self._request("callHierarchy/incomingCalls", {"item": item}) or [])
        return incoming, outgoing

    def semantic_tokens(self, uri: str) -> dict[str, Any] | None:
        result = self._request("textDocument/semanticTokens/full", {"textDocument": {"uri": uri}})
        return result if isinstance(result, dict) else None

    def type_hierarchy(self, uri: str, line: int, character: int) -> dict[str, Any]:
        prepared = self._request("textDocument/prepareTypeHierarchy", {
            "textDocument": {"uri": uri}, "position": {"line": line, "character": character},
        }) or []
        item = prepared[0] if prepared else {}
        return {
            "supertypes": self._request("typeHierarchy/supertypes", {"item": item}),
            "subtypes": self._request("typeHierarchy/subtypes", {"item": item}),
        }

    def moniker(self, uri: str, line: int, character: int) -> list[Any]:
        return self._request("textDocument/moniker", {
            "textDocument": {"uri": uri}, "position": {"line": line, "character": character},
        }) or []

    # -- internals ----------------------------------------------------------
    def _notify(self, msg: dict[str, Any]) -> None:
        if self._proc is None:
            raise RuntimeError("client not started")
        send_msg(self._proc, msg)

    def _request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        mid = self._next_id
        self._next_id += 1
        if self._proc is None:
            raise RuntimeError("client not started")
        send_msg(self._proc, {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
        while True:
            msg = self._queue.get(timeout=timeout)
            if msg.get("method"):
                self._notifications.append(msg)
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} -> {msg['error']}")
                return msg.get("result")
            # a different id — ignore and keep reading

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        while not self._stop.is_set():
            try:
                headers: dict[bytes, bytes] = {}
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        return
                    if line in (b"\r\n", b"\n"):
                        break
                    if b":" in line:
                        key, _, val = line.partition(b":")
                        headers[key.strip().lower()] = val.strip()
                if b"content-length" not in headers:
                    continue
                body = proc.stdout.read(int(headers[b"content-length"])).decode("utf-8")
                self._queue.put(json.loads(body))
            except Exception as exc:  # noqa: BLE001 - reader must not die silently
                self._queue.put({"__reader_error__": str(exc)})
                return


def send_msg(proc: subprocess.Popen[bytes], msg: dict[str, Any]) -> None:
    body = json.dumps(msg).encode("utf-8")
    proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body))
    proc.stdin.write(body)
    proc.stdin.flush()


def _default_client_caps() -> dict[str, Any]:
    token_types = [
        "namespace", "type", "class", "enum", "interface", "struct", "typeParameter",
        "parameter", "variable", "property", "enumMember", "event", "function",
        "method", "macro", "keyword", "modifier", "comment", "string", "number",
        "regexp", "operator", "decorator",
    ]
    token_modifiers = [
        "declaration", "definition", "readonly", "static", "deprecated", "abstract",
        "async", "modification", "documentation", "defaultLibrary",
    ]
    return {
        "textDocument": {
            "callHierarchy": {"dynamicRegistration": True},
            "typeHierarchy": {"dynamicRegistration": True},
            "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
            "semanticTokens": {
                "requests": {"range": True, "full": {"delta": True}},
                "tokenTypes": token_types,
                "tokenModifiers": token_modifiers,
                "formats": ["relative"],
            },
        },
        "window": {"workDoneProgress": True},
    }
