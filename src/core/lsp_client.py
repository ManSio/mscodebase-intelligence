"""MSCodeBase LSP client — thin capability-aware engine + production async facade.

Two layers in one module:

1. ``_LspEngine`` — the thin, self-contained transport core (port of the
   experiment harness in ``experiments/lsp/thin_client.py``, live-validated
   2026-08-19 against basedpyright 1.39.10: call hierarchy + semantic tokens).
   It is *synchronous*: owns the subprocess, a reader thread and a queue, and
   speaks real ``Content-Length`` framed JSON-RPC. It is capability-agnostic
   and deliberately has no product logic.

2. ``LspClient`` — the production async facade. It is the drop-in for the
   legacy client used by ``write_tools`` (preflight validation, rename with
   LSP fallback) and ``lsp_tools`` (find def/refs, symbols, code actions,
   diagnostics, hover, type info). It wraps every engine call in a single
   ``asyncio.Lock`` + ``asyncio.to_thread`` so the blocking engine never
   blocks the event loop and requests never interleave (id-correlation is
   safe because only one request is in flight at a time).

The facade reconstructs the observable API of the legacy client exactly:
constructor ``LspClient(project_root=..., language=...)``, async document
methods, ``_process`` attribute, module-level ``create_lsp_client`` and the
staticmethod URI helpers required by ``tests/test_lsp_uri_conversion.py`` and
``tests/test_lsp_tools.py``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


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


def send_msg(proc: subprocess.Popen[bytes], msg: dict[str, Any]) -> None:
    body = json.dumps(msg).encode("utf-8")
    proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body))
    proc.stdin.write(body)
    proc.stdin.flush()


class _LspEngine:
    """Synchronous, capability-probing stdio LSP transport (experiment core).

    One reader thread owns stdout; callers own stdin. Requests are matched by
    id. ``textDocument/publishDiagnostics`` notifications are captured into
    ``self.diagnostics`` (canonical uri -> list) regardless of pending requests,
    so the async facade can wait for fresh diagnostics.
    """

    def __init__(self, language: str, specs: dict[str, ServerSpec] | None = None) -> None:
        spec = (specs or DEFAULT_SERVERS).get(language)
        if spec is None:
            raise ValueError(f"no server spec for language={language!r}")
        self.language = language
        self.spec = spec
        self._proc: subprocess.Popen[bytes] | None = None
        self._queue: queue.Queue[dict[str, object]] = queue.Queue()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._next_id = 1
        self._notifications: list[dict[str, Any]] = []
        self.diagnostics: dict[str, list[Any]] = {}
        self.capabilities: dict[str, Any] = {}
        self.server_info: dict[str, Any] = {}

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

    def __enter__(self) -> "_LspEngine":
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
                msg = json.loads(body)
                self._capture_diagnostics(msg)
                self._queue.put(msg)
            except Exception as exc:  # noqa: BLE001 - reader must not die silently
                self._queue.put({"__reader_error__": str(exc)})
                return

    def _capture_diagnostics(self, msg: dict[str, Any]) -> None:
        """Persist publishDiagnostics notifications for the async facade."""
        try:
            if msg.get("method") == "textDocument/publishDiagnostics":
                params = msg.get("params") or {}
                uri = str(params.get("uri", ""))
                # LspClient resolved at runtime — module fully loaded by then.
                self.diagnostics[LspClient._normalize_diag_uri(uri)] = list(
                    params.get("diagnostics") or []
                )
        except Exception:  # noqa: BLE001 - capture must never kill the reader
            pass


class LspClient:
    """Production async facade over ``_LspEngine``.

    Drop-in for the legacy client consumed by ``write_tools`` and ``lsp_tools``.
    All engine access is serialized through a single lock and offloaded to a
    thread so the synchronous engine never blocks the event loop and requests
    never interleave.
    """

    MAX_RETRIES = 3
    START_TIMEOUT = 40.0

    def __init__(self, project_root: Path, language: str = "python"):
        self.project_root = Path(project_root)
        self.language = language
        self._engine: Optional[_LspEngine] = None
        self._process: Optional[subprocess.Popen] = None
        self._started = False
        self._stopped = False
        self._open_files: set[str] = set()
        self._doc_versions: dict[str, int] = {}
        self._retries = 0
        self._start_lock = asyncio.Lock()
        self._op_lock = asyncio.Lock()

    # ── lifecycle ─────────────────────────────────────────────────────────
    async def start(self) -> bool:
        if self._started:
            return True
        if self._engine is None:
            try:
                self._engine = _LspEngine(self.language)
            except ValueError as exc:
                logger.warning("LSP: %s", exc)
                return False
        try:
            root_uri = self._path_to_uri(str(self.project_root))
            await asyncio.to_thread(
                self._engine.start, root_uri, str(self.project_root), None, self.START_TIMEOUT
            )
            self._process = self._engine._proc
            self._started = True
            self._retries = 0
            logger.info("LSP ready (pid=%s)", getattr(self._process, "pid", "?"))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("LSP start failed: %s", exc)
            await self.stop()
            return False

    async def stop(self) -> None:
        self._stopped = True
        eng = self._engine
        self._engine = None
        self._process = None
        self._started = False
        self._open_files.clear()
        self._doc_versions.clear()
        if eng is not None:
            try:
                await asyncio.to_thread(eng.stop)
            except Exception as exc:  # noqa: BLE001
                logger.debug("LSP close failed: %s", exc)

    async def is_ready(self) -> bool:
        if self._stopped:
            return False
        eng = self._engine
        if (
            self._started
            and eng is not None
            and eng._proc is not None
            and eng._proc.returncode is None
        ):
            return True
        return False

    async def _ensure_started(self) -> bool:
        """Lazy start on first request. Auto-restarts on crash."""
        if await self.is_ready():
            return True
        if self._stopped:
            return False
        async with self._start_lock:
            if await self.is_ready():
                return True
            if self._retries >= self.MAX_RETRIES:
                logger.error("LSP max retries (%d/%d) reached", self._retries, self.MAX_RETRIES)
                return False
            self._retries += 1
            return await self.start()

    # ── serialized engine access ──────────────────────────────────────────
    async def _send_request(self, method: str, params: Optional[dict] = None) -> Any:
        eng = self._engine
        if eng is None:
            raise RuntimeError("client not started")
        async with self._op_lock:
            return await asyncio.to_thread(eng._request, method, params or {})

    async def _send_notification(self, method: str, params: dict) -> None:
        eng = self._engine
        if eng is None:
            raise RuntimeError("client not started")
        async with self._op_lock:
            await asyncio.to_thread(
                eng._notify, {"jsonrpc": "2.0", "method": method, "params": params}
            )

    # ── document methods ──────────────────────────────────────────────────
    async def open_file(self, file_path: str) -> bool:
        """Send textDocument/didOpen. Returns True when file is tracked."""
        if not await self._ensure_started():
            return False
        abs_path = str(Path(file_path).resolve())
        if abs_path in self._open_files:
            return True
        content = self._read_file_content(abs_path)
        if content is None:
            return False
        await self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": self._path_to_uri(abs_path),
                "languageId": self._language_id(),
                "version": 1,
                "text": content,
            },
        })
        self._open_files.add(abs_path)
        return True

    async def close_file(self, file_path: str) -> None:
        """Send textDocument/didClose."""
        abs_path = str(Path(file_path).resolve())
        if abs_path not in self._open_files:
            return
        if self._started and self._engine is not None:
            await self._send_notification("textDocument/didClose", {
                "textDocument": {"uri": self._path_to_uri(abs_path)},
            })
        self._open_files.discard(abs_path)

    async def find_definition(self, file_path: str, line: int, col: int) -> List[Dict[str, Any]]:
        """textDocument/definition -> list of locations."""
        return await self._send_text_request("textDocument/definition", file_path, line, col)

    async def find_references(self, file_path: str, line: int, col: int) -> List[Dict[str, Any]]:
        """textDocument/references -> list of locations."""
        return await self._send_text_request(
            "textDocument/references", file_path, line, col,
            extra={"context": {"includeDeclaration": True}},
        )

    async def rename_symbol(
        self,
        file_path: str,
        line: int,
        col: int = -1,
        new_name: str = "",
        old_name: str = "",
    ) -> Optional[Dict[str, Any]]:
        """textDocument/rename -> Optional[WorkspaceEdit].

        If col == -1, auto-detects the column by scanning the line for old_name.
        """
        if not await self._ensure_started():
            return None
        if not await self.open_file(file_path):
            return None
        if col < 0:
            search_name = old_name or new_name
            col = self._find_symbol_column(file_path, line, search_name)
            if col < 0:
                # col=0 as fallback would rename the wrong symbol (first on line).
                logger.warning(
                    "rename_symbol: cannot locate '%s' on line %d — aborting",
                    search_name, line,
                )
                return None
        try:
            return await self._send_request("textDocument/rename", {
                "textDocument": {"uri": self._path_to_uri(file_path)},
                "position": {"line": line, "character": col},
                "newName": new_name,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("rename_symbol failed: %s", exc)
            return None

    async def document_symbols(self, file_path: str) -> List[Dict[str, Any]]:
        """textDocument/documentSymbol -> list of symbols."""
        if not await self._ensure_started():
            return []
        if not await self.open_file(file_path):
            return []
        try:
            result = await self._send_request("textDocument/documentSymbol", {
                "textDocument": {"uri": self._path_to_uri(file_path)},
            })
            return result if isinstance(result, list) else []
        except Exception as exc:  # noqa: BLE001
            logger.warning("document_symbols failed: %s", exc)
            return []

    async def code_actions(self, file_path: str, line: int, col: int) -> List[Dict[str, Any]]:
        """textDocument/codeAction -> список быстрых правок (CodeAction).

        Read-only: pyright computes quickfixes from its own analysis; context
        diagnostics are left empty (the editor need not supply them).
        """
        if not await self._ensure_started():
            return []
        if not await self.open_file(file_path):
            return []
        try:
            result = await self._send_request("textDocument/codeAction", {
                "textDocument": {"uri": self._path_to_uri(file_path)},
                "range": {
                    "start": {"line": line, "character": col},
                    "end": {"line": line, "character": col},
                },
                "context": {"diagnostics": []},
            })
            return result if isinstance(result, list) else []
        except Exception as exc:  # noqa: BLE001
            logger.warning("code_actions failed: %s", exc)
            return []

    async def hover(self, file_path: str, line: int, col: int) -> Optional[str]:
        """textDocument/hover -> human-readable string."""
        result = await self._send_text_request("textDocument/hover", file_path, line, col)
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return self._format_hover(result[0].get("contents"))
        if isinstance(result, dict):
            return self._format_hover(result.get("contents"))
        if isinstance(result, str):
            return result
        return None

    async def get_diagnostics(self, file_path: str, wait_ms: int = 800) -> List[Dict[str, Any]]:
        """textDocument/publishDiagnostics -> list of diagnostics for the file.

        basedpyright publishes diagnostics asynchronously after didOpen; wait up
        to wait_ms for a FRESH publish. The stored entry is cleared first so we
        never return stale data.
        """
        if not await self._ensure_started():
            return []
        abs_path = str(Path(file_path).resolve())
        uri = self._path_to_uri(abs_path)
        if not await self.open_file(abs_path):
            return []
        eng = self._engine
        if eng is None:
            return []
        eng.diagnostics.pop(uri, None)
        deadline = time.monotonic() + wait_ms / 1000.0
        while time.monotonic() < deadline:
            if uri in eng.diagnostics:
                return list(eng.diagnostics.get(uri, []))
            await asyncio.sleep(0.05)
        return list(eng.diagnostics.get(uri, []))

    async def preflight_content(
        self, file_path: str, new_content: str, wait_ms: int = 1200
    ) -> List[Dict[str, Any]]:
        """Check NEW content of a file through LSP without writing to disk.

        Sends didChange (or didOpen for a new file) with new_content, waits for
        publishDiagnostics, then rolls the change back (didChange back to disk
        content / didClose) so the LSP session is not poisoned for later calls
        (rename, etc.). Returns diagnostics for new_content (may be empty);
        empty on LSP unavailable / error (advisory).
        """
        if not await self._ensure_started():
            return []
        abs_path = str(Path(file_path).resolve())
        uri = self._path_to_uri(abs_path)
        eng = self._engine
        if eng is None:
            return []
        was_open = abs_path in self._open_files
        try:
            if not was_open:
                await self._send_notification("textDocument/didOpen", {
                    "textDocument": {
                        "uri": uri,
                        "languageId": self._language_id(),
                        "version": 1,
                        "text": new_content,
                    },
                })
                self._open_files.add(abs_path)
                self._doc_versions[abs_path] = 1
            else:
                version = self._doc_versions.get(abs_path, 1) + 1
                self._doc_versions[abs_path] = version
                await self._send_notification("textDocument/didChange", {
                    "textDocument": {"uri": uri, "version": version},
                    "contentChanges": [{"text": new_content}],
                })
            eng.diagnostics.pop(uri, None)
            result: List[Dict[str, Any]] = []
            deadline = time.monotonic() + wait_ms / 1000.0
            while time.monotonic() < deadline:
                if uri in eng.diagnostics:
                    result = list(eng.diagnostics.get(uri, []))
                    break
                await asyncio.sleep(0.05)
            return result
        finally:
            # Roll back the LSP session to disk content.
            try:
                original = self._read_file_content(abs_path)
                if was_open:
                    if original is not None:
                        version = self._doc_versions.get(abs_path, 1) + 1
                        self._doc_versions[abs_path] = version
                        await self._send_notification("textDocument/didChange", {
                            "textDocument": {"uri": uri, "version": version},
                            "contentChanges": [{"text": original}],
                        })
                else:
                    self._open_files.discard(abs_path)
                    self._doc_versions.pop(abs_path, None)
                    if self._started and self._engine is not None:
                        await self._send_notification("textDocument/didClose", {
                            "textDocument": {"uri": uri},
                        })
            except Exception as exc:  # noqa: BLE001
                logger.warning("preflight revert failed for %s: %s", abs_path, exc)

    async def completion(self, file_path: str, line: int, col: int) -> List[Dict[str, Any]]:
        """textDocument/completion -> list of CompletionItem."""
        if not await self._ensure_started():
            return []
        if not await self.open_file(file_path):
            return []
        try:
            result = await self._send_request("textDocument/completion", {
                "textDocument": {"uri": self._path_to_uri(file_path)},
                "position": {"line": line, "character": col},
            })
            if isinstance(result, dict):
                return result.get("items", [])
            return result if isinstance(result, list) else []
        except Exception as exc:  # noqa: BLE001
            logger.warning("completion failed: %s", exc)
            return []

    # ── text request helper ───────────────────────────────────────────────
    async def _send_text_request(
        self,
        method: str,
        file_path: str,
        line: int,
        col: int,
        extra: Optional[dict] = None,
    ) -> List[Dict[str, Any]]:
        """Open file then send textDocument/*. Returns list (single dict wrapped)."""
        if not await self._ensure_started():
            return []
        if not await self.open_file(file_path):
            return []
        params: dict[str, Any] = {
            "textDocument": {"uri": self._path_to_uri(file_path)},
            "position": {"line": line, "character": col},
        }
        if extra:
            params.update(extra)
        try:
            result = await self._send_request(method, params)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s failed: %s", method, exc)
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and ("uri" in result or "range" in result):
            return [result]
        return []

    # ── small helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _read_file_content(file_path: str) -> Optional[str]:
        try:
            return Path(file_path).read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.warning("Cannot read '%s': %s", file_path, exc)
            return None

    def _language_id(self) -> str:
        mapping = {
            "python": "python", "typescript": "typescript", "javascript": "javascript",
            "html": "html", "css": "css", "json": "json", "yaml": "yaml", "markdown": "markdown",
        }
        return mapping.get(self.language, self.language)

    @staticmethod
    def _find_symbol_column(file_path: str, line_0based: int, symbol_name: str) -> int:
        """Auto-detect column position of symbol_name on the given line.

        LSP needs the cursor position WITHIN the symbol name, not at column 0.
        Returns -1 if not found (fallback to col=0).
        """
        if not symbol_name:
            return -1
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            if 0 <= line_0based < len(lines):
                line_text = lines[line_0based]
                # Word-boundary: match the token, not a substring
                # (foo in foo_bar or inside a string literal is not the same).
                m = re.search(rf"\b{re.escape(symbol_name)}\b", line_text)
                if m:
                    return m.start()
        except Exception:  # noqa: BLE001
            logger.warning("exception", exc_info=True)
        return -1

    @staticmethod
    def _format_hover(contents: Any) -> Optional[str]:
        if contents is None:
            return None
        if isinstance(contents, str):
            return contents
        if isinstance(contents, dict):
            return contents.get("value", str(contents))
        if isinstance(contents, list):
            parts = []
            for item in contents:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("value", str(item)))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(contents)

    @staticmethod
    def _path_to_uri(path: str) -> str:
        """Convert a filesystem path to a file:// URI (including UNC paths).

        Path.as_uri() correctly handles UNC (double backslash server + share,
        then file -> file://server/share/file) and Windows drives (C:\\x ->
        file:///C:/x).
        """
        try:
            return Path(path).resolve().as_uri()
        except (ValueError, OSError):
            # Invalid/unreachable path. OSError: Python 3.10-3.12 realpath raises
            # FileNotFoundError for a nonexistent UNC server (3.13+ does not) —
            # take path as-is (UNC stays absolute).
            return Path(path).as_uri()

    @staticmethod
    def _uri_to_path(uri: str) -> str:
        parsed = urlparse(uri)
        raw = parsed.path
        # UNC URI (file://server/share/file) — the authority is the server.
        if parsed.netloc and parsed.netloc not in ("localhost", "127.0.0.1"):
            p = Path("//" + parsed.netloc + raw)
            try:
                return p.resolve().as_posix()
            except OSError:  # 3.10-3.12: realpath UNC server -> FileNotFoundError
                return p.as_posix()
        if len(raw) > 2 and raw[0] == "/" and raw[2] == ":":
            raw = raw[1:]
        return Path(raw).resolve().as_posix()

    @staticmethod
    def _normalize_diag_uri(uri: str) -> str:
        """Bring a publishDiagnostics-uri to the client's canonical form.

        basedpyright on Windows re-encodes the uri (file:///D:/x ->
        file:///d%3A/x: lowercase drive + percent-encoding). The client sends
        Path.as_uri() and looks up by it. Without normalization diagnostics are
        silently lost (key mismatch).
        """
        try:
            parsed = urlparse(unquote(uri))
            raw = parsed.path
            if parsed.netloc and parsed.netloc not in ("localhost", "127.0.0.1"):
                p = Path("//" + parsed.netloc + raw)
                try:
                    return p.resolve().as_uri()
                except OSError:  # 3.10-3.12: realpath UNC server -> FileNotFoundError
                    return p.as_uri()
            if len(raw) > 2 and raw[0] == "/" and raw[2] == ":":
                raw = raw[1:]
            return Path(raw).resolve().as_uri()
        except Exception:  # noqa: BLE001
            return uri


async def create_lsp_client(project_root: Path, language: str = "python") -> LspClient:
    """Create and start an LspClient. Returns ready or fallback instance."""
    client = LspClient(project_root, language)
    await client.start()
    if not client._started:
        logger.info("LSP unavailable — graceful fallback to SymbolIndex")
    return client


__all__ = ["LspClient", "create_lsp_client"]
