"""
Thin LSP client: spawns pyright-langserver as subprocess,
JSON-RPC 2.0 over stdin/stdout. Lazy-start, auto-restart.
Falls back to SymbolIndex when LSP unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

logger = logging.getLogger("mscodebase_server.lsp_client")


class LspClient:
    """Thin LSP client for language servers via stdio JSON-RPC 2.0.

    Starts the language server as a subprocess on demand (lazy).
    Auto-restarts on crash up to MAX_RETRIES attempts.
    """

    START_TIMEOUT = 10.0
    MAX_RETRIES = 3
    REQUEST_TIMEOUT = 5.0
    BUFFER_SIZE = 65536

    def __init__(self, project_root: Path, language: str = "python"):
        self.project_root = project_root
        self.language = language
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 1
        self._pending: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._start_lock = asyncio.Lock()
        self._started = False
        self._retries = 0
        self._capabilities: Dict[str, Any] = {}
        self._open_files: Set[str] = set()
        self._stopped = False

    # ── Public API ────────────────────────────────────────────────────────

    async def start(self) -> bool:
        """Start the language server subprocess. Returns True if ready."""
        server_cmd = self._find_server()
        if server_cmd is None:
            logger.warning("LSP server not found for language=%s", self.language)
            return False
        logger.info("Starting LSP: %s", server_cmd)
        try:
            self._process = await asyncio.create_subprocess_exec(
                server_cmd,
                "--stdio",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except (FileNotFoundError, PermissionError) as exc:
            logger.error("Failed to start LSP '%s': %s", server_cmd, exc)
            return False
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_consumer())
        try:
            result = await asyncio.wait_for(self._initialize(), timeout=self.START_TIMEOUT)
            self._capabilities = result.get("capabilities", {})
            self._started = True
            self._retries = 0
            logger.info("LSP ready (pid=%d)", self._process.pid)
            return True
        except asyncio.TimeoutError:
            logger.error("LSP start timed out (%.1fs)", self.START_TIMEOUT)
            await self.stop()
            return False
        except Exception as exc:
            logger.error("LSP init failed: %s", exc)
            await self.stop()
            return False

    async def stop(self):
        """Shut down the language server."""
        self._stopped = True
        if self._process is not None and self._process.returncode is None:
            try:
                await self._send_request("shutdown", {})
            except Exception:
                pass
            self._send_notification("exit", {})
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._reader_task = self._stderr_task = None
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass
        self._process = None
        self._started = False
        self._open_files.clear()
        for f in self._pending.values():
            if not f.done():
                f.set_exception(RuntimeError("LSP stopped"))
        self._pending.clear()

    async def is_ready(self) -> bool:
        """Non-blocking check if LSP server is started and responsive.

        Returns True if the server process is running and initialized.
        Does NOT attempt to start the server (use _ensure_started for that).
        """
        if self._stopped:
            return False
        if self._started and self._process is not None and self._process.returncode is None:
            return True
        return False

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
        self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": self._path_to_uri(abs_path),
                "languageId": self._language_id(),
                "version": 1,
                "text": content,
            },
        })
        self._open_files.add(abs_path)
        return True

    async def close_file(self, file_path: str):
        """Send textDocument/didClose."""
        abs_path = str(Path(file_path).resolve())
        if abs_path not in self._open_files:
            return
        if self._started and self._process is not None:
            self._send_notification("textDocument/didClose", {
                "textDocument": {"uri": self._path_to_uri(abs_path)},
            })
        self._open_files.discard(abs_path)

    async def find_definition(self, file_path: str, line: int, col: int) -> List[Dict[str, Any]]:
        """textDocument/definition → list of locations."""
        return await self._send_text_request("textDocument/definition", file_path, line, col)

    async def find_references(self, file_path: str, line: int, col: int) -> List[Dict[str, Any]]:
        """textDocument/references → list of locations."""
        return await self._send_text_request(
            "textDocument/references", file_path, line, col,
            extra={"context": {"includeDeclaration": True}},
        )

    async def rename_symbol(self, file_path: str, line: int, col: int = -1, new_name: str = "", old_name: str = "") -> Optional[Dict[str, Any]]:
        """textDocument/rename → Optional[WorkspaceEdit].

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
                col = 0  # fallback
        try:
            return await self._send_request("textDocument/rename", {
                "textDocument": {"uri": self._path_to_uri(file_path)},
                "position": {"line": line, "character": col},
                "newName": new_name,
            })
        except Exception as exc:
            logger.warning("rename_symbol failed: %s", exc)
            self._handle_crash()
            return None

    async def document_symbols(self, file_path: str) -> List[Dict[str, Any]]:
        """textDocument/documentSymbol → list of symbols."""
        if not await self._ensure_started():
            return []
        if not await self.open_file(file_path):
            return []
        try:
            result = await self._send_request("textDocument/documentSymbol", {
                "textDocument": {"uri": self._path_to_uri(file_path)},
            })
            return result if isinstance(result, list) else []
        except Exception as exc:
            logger.warning("document_symbols failed: %s", exc)
            self._handle_crash()
            return []

    async def hover(self, file_path: str, line: int, col: int) -> Optional[str]:
        """textDocument/hover → human-readable string."""
        result = await self._send_text_request("textDocument/hover", file_path, line, col)
        if isinstance(result, dict):
            return self._format_hover(result.get("contents"))
        if isinstance(result, str):
            return result
        return None

    async def completion(self, file_path: str, line: int, col: int) -> List[Dict[str, Any]]:
        """textDocument/completion → list of CompletionItem."""
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
        except Exception as exc:
            logger.warning("completion failed: %s", exc)
            self._handle_crash()
            return []

    # ── Internal lifecycle ────────────────────────────────────────────────

    async def _ensure_started(self) -> bool:
        """Lazy start on first request. Auto-restarts on crash."""
        if self._is_alive():
            return True
        if self._stopped:
            return False
        async with self._start_lock:
            if self._is_alive():
                return True
            if self._retries >= self.MAX_RETRIES:
                logger.error("LSP max retries (%d/%d) reached", self._retries, self.MAX_RETRIES)
                return False
            self._retries += 1
            return await self.start()

    def _is_alive(self) -> bool:
        return self._started and self._process is not None and self._process.returncode is None

    async def _initialize(self) -> dict:
        """Send initialize request with Zed-pyright specific options.

        Key options:
        - openFilesOnly: True — pyright only indexes files we didOpen
        - venvPath: project root — so pyright finds local .venv
        - pythonPath: sys.executable — same Python as MCP
        """
        root_uri = self._path_to_uri(str(self.project_root))
        result = await self._send_request("initialize", {
            "processId": os.getpid(),
            "rootPath": str(self.project_root),
            "rootUri": root_uri,
            "clientInfo": {"name": "mscodebase-server", "version": "1.0"},
            "capabilities": {
                "textDocument": {
                    "rename": {"dynamicRegistration": True},
                    "references": {"dynamicRegistration": True},
                    "definition": {"dynamicRegistration": True},
                    "hover": {"dynamicRegistration": True},
                    "documentSymbol": {"dynamicRegistration": True},
                },
                "workspace": {
                    "workspaceEdit": {"documentChanges": True},
                    "workspaceFolders": True,
                },
            },
            "initializationOptions": {
                "openFilesOnly": True,
                "pythonPath": sys.executable,
                "venvPath": str(self.project_root),
            },
            "workspaceFolders": [
                {"uri": root_uri, "name": self.project_root.name},
            ],
        })
        self._send_notification("initialized", {})
        return result

    def _handle_crash(self):
        """Reset internal state so next call triggers auto-restart."""
        if self._stopped:
            return
        self._started = False
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
        self._reader_task = self._stderr_task = None
        self._process = None
        for f in self._pending.values():
            if not f.done():
                f.set_exception(RuntimeError("LSP crashed"))
        self._pending.clear()

    # ── Server discovery ──────────────────────────────────────────────────

    def _find_server(self) -> Optional[str]:
        """Find language server binary: PATH → Zed LSP dirs → venvs → project venvs."""
        if self.language == "python":
            if sys.platform == "win32":
                candidates = ["pyright-langserver.cmd", "pyright-langserver", "pyright-langserver.exe"]
            else:
                candidates = ["pyright-langserver", "pyright-langserver.exe"]
        elif self.language in ("typescript", "javascript"):
            candidates = ["typescript-language-server", "typescript-language-server.cmd"]
        else:
            logger.warning("Unsupported LSP language: %s", self.language)
            return None

        # 1. Поиск в PATH (самый быстрый)
        for cmd in candidates:
            found = shutil.which(cmd)
            if found:
                return found

        # 2. Поиск в Zed LSP директориях (Zed управляет pyright сам!)
        # Имя папки = имя LSP сервера, а не языка (pyright, а не python)
        lsp_name = "pyright" if self.language == "python" else "typescript-language-server"
        zed_lsp_dirs = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Zed" / "languages" / lsp_name / "node_modules" / ".bin",
        ]
        # basedpyright — альтернатива
        if self.language == "python":
            zed_lsp_dirs.append(
                Path(os.environ.get("LOCALAPPDATA", "")) / "Zed" / "languages" / "basedpyright" / "node_modules" / ".bin"
            )
        for d in zed_lsp_dirs:
            for cmd in candidates:
                candidate = d / cmd
                if candidate.is_file():
                    return str(candidate.resolve())

        # 3. Поиск в venv текущего Python
        search_dirs: List[Path] = []
        if hasattr(sys, "prefix") and sys.prefix:
            p = Path(sys.prefix)
            search_dirs.extend([p / "bin", p / "Scripts"])

        # 4. Поиск в project venvs
        for venv_name in (".venv", "venv", ".env"):
            search_dirs.extend([
                self.project_root / venv_name / "bin",
                self.project_root / venv_name / "Scripts",
            ])

        for d in search_dirs:
            for cmd in candidates:
                candidate = d / cmd
                if candidate.is_file():
                    return str(candidate.resolve())

        return None

    # ── Wire protocol ─────────────────────────────────────────────────────

    async def _send_request(self, method: str, params: dict) -> Any:
        """Send JSON-RPC 2.0 request → await response. Raises on error/timeout."""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("LSP not running")
        req_id = self._request_id
        self._request_id += 1
        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        self._write_message(json.dumps(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
            ensure_ascii=False, separators=(",", ":"),
        ))
        await self._process.stdin.drain()
        try:
            response = await asyncio.wait_for(future, timeout=self.REQUEST_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise RuntimeError(f"LSP '{method}' timed out ({self.REQUEST_TIMEOUT}s)")
        if "error" in response:
            e = response["error"]
            raise RuntimeError(f"LSP error ({method}): {e.get('message', '?')} [code={e.get('code', -1)}]")
        return response.get("result")

    def _send_notification(self, method: str, params: dict):
        """Fire-and-forget JSON-RPC 2.0 notification."""
        if self._process is None or self._process.stdin is None:
            return
        try:
            self._write_message(json.dumps(
                {"jsonrpc": "2.0", "method": method, "params": params},
                ensure_ascii=False, separators=(",", ":"),
            ))
        except Exception as exc:
            logger.warning("notify '%s' failed: %s", method, exc)

    def _write_message(self, body: str):
        """Write Content-Length framed message to subprocess stdin."""
        data = body.encode("utf-8")
        raw = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data
        if self._process and self._process.stdin:
            self._process.stdin.write(raw)

    # ── Read loop (response dispatcher) ───────────────────────────────────

    async def _read_loop(self):
        """Background: read Content-Length framed responses from stdout → dispatch."""
        try:
            buf = bytearray()
            while self._process is not None and self._process.stdout is not None:
                chunk = await self._process.stdout.read(self.BUFFER_SIZE)
                if not chunk:
                    if not self._stopped:
                        self._handle_crash()
                    break
                buf.extend(chunk)
                while True:
                    resp, consumed = self._parse_one(buf)
                    if resp is None:
                        break
                    buf = buf[consumed:]
                    resp_id = resp.get("id")
                    if resp_id is not None and resp_id in self._pending:
                        fut = self._pending.pop(resp_id)
                        if not fut.done():
                            fut.set_result(resp)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if not self._stopped:
                logger.error("LSP read loop: %s", exc)
                self._handle_crash()

    @staticmethod
    def _parse_one(buf: bytearray) -> tuple[Optional[dict], int]:
        """Parse one Content-Length frame from buffer head → (dict|None, bytes_consumed)."""
        hdr_end = buf.find(b"\r\n\r\n")
        if hdr_end == -1:
            return None, 0
        headers = {}
        for line in buf[:hdr_end].split(b"\r\n"):
            if b":" in line:
                # Convert bytearray→bytes to avoid 'unhashable type' in Python 3.14+
                k, v = bytes(line).split(b":", 1)
                headers[k.strip().lower()] = v.strip()
        cl = headers.get(b"content-length")
        if cl is None:
            return None, hdr_end + 4
        length = int(cl)
        body_start = hdr_end + 4
        if len(buf) < body_start + length:
            return None, 0
        try:
            return json.loads(buf[body_start:body_start + length]), body_start + length
        except json.JSONDecodeError:
            return {}, body_start + length

    async def _stderr_consumer(self):
        """Background: log stderr at debug level."""
        try:
            while self._process is not None and self._process.stderr is not None:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.rstrip(b"\r\n").decode("utf-8", errors="replace")
                if text:
                    logger.debug("[LSP stderr] %s", text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if not self._stopped:
                logger.debug("stderr consumer: %s", exc)

    # ── Text request helper ───────────────────────────────────────────────

    async def _send_text_request(
        self, method: str, file_path: str, line: int, col: int,
        extra: Optional[dict] = None,
    ) -> List[Dict[str, Any]]:
        """Open file then send textDocument/*. Returns list (possibly single dict wrapped)."""
        if not await self._ensure_started():
            return []
        if not await self.open_file(file_path):
            return []
        params = {
            "textDocument": {"uri": self._path_to_uri(file_path)},
            "position": {"line": line, "character": col},
        }
        if extra:
            params.update(extra)
        try:
            result = await self._send_request(method, params)
        except Exception as exc:
            logger.warning("%s failed: %s", method, exc)
            self._handle_crash()
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and ("uri" in result or "range" in result):
            return [result]
        return []

    # ── Small helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _read_file_content(file_path: str) -> Optional[str]:
        try:
            return Path(file_path).read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.warning("Cannot read '%s': %s", file_path, exc)
            return None

    def _language_id(self) -> str:
        mapping = {"python": "python", "typescript": "typescript", "javascript": "javascript",
                    "html": "html", "css": "css", "json": "json", "yaml": "yaml", "markdown": "markdown"}
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
                idx = line_text.find(symbol_name)
                if idx >= 0:
                    return idx
        except Exception:
            pass
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
        abs_path = Path(path).resolve()
        posix = abs_path.as_posix()
        return "file:///" + posix.lstrip("/") if posix.startswith("/") else "file:///" + posix

    @staticmethod
    def _uri_to_path(uri: str) -> str:
        parsed = urlparse(uri)
        raw = parsed.path
        if len(raw) > 2 and raw[0] == "/" and raw[2] == ":":
            raw = raw[1:]
        return Path(raw).resolve().as_posix()


async def create_lsp_client(project_root: Path, language: str = "python") -> LspClient:
    """Create and start an LspClient. Returns ready or fallback instance."""
    client = LspClient(project_root, language)
    await client.start()
    if not client._started:
        logger.info("LSP unavailable — graceful fallback to SymbolIndex")
    return client


__all__ = ["LspClient", "create_lsp_client"]
