"""Regression guard for the production LspClient facade (drop-in contract).

The production ``src/core/lsp_client`` was rebuilt on top of the thin
experiment engine (``_LspEngine``). These tests pin the observable contract
that ``write_tools`` and ``lsp_tools`` depend on, so a future rewrite that
silently changes the API surface or fails to fall back gracefully is caught.
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import src.core.lsp_client as lc
from src.core.lsp_client import LspClient, create_lsp_client

DOCUMENT_API = (
    "start", "stop", "is_ready", "open_file", "close_file",
    "find_definition", "find_references", "rename_symbol",
    "document_symbols", "code_actions", "hover",
    "get_diagnostics", "preflight_content", "completion",
)


def test_facade_document_api_surface():
    """Every method the production consumers call must exist and be async."""
    c = LspClient(project_root=Path("."))
    for name in DOCUMENT_API:
        method = getattr(c, name, None)
        assert method is not None, f"missing async method: {name}"
        assert inspect.iscoroutinefunction(method), f"not a coroutine fn: {name}"
    # lsp_tools reads client._process after start; must exist even before.
    assert hasattr(c, "_process")


def test_facade_static_helpers_present():
    """Static helpers consumed by tests/tools must be real staticmethods."""
    for name in (
        "_path_to_uri", "_uri_to_path", "_normalize_diag_uri",
        "_format_hover", "_find_symbol_column", "_read_file_content",
    ):
        assert name in LspClient.__dict__, f"missing static helper: {name}"
        assert isinstance(LspClient.__dict__[name], staticmethod), f"not static: {name}"


def test_create_lsp_client_exists():
    assert inspect.iscoroutinefunction(create_lsp_client)


def test_graceful_fallback_without_server(monkeypatch, tmp_path):
    """start() must return False (never crash) when the server binary is absent.

    This is the fail-soft contract behind the SymbolIndex fallback: LSP
    unavailable is INCONCLUSIVE/degraded, not an exception.
    """
    monkeypatch.setattr(lc, "DEFAULT_SERVERS", {
        "python": lc.ServerSpec("python", ["/nonexistent/basedpyright-langserver", "--stdio"]),
    })
    c = LspClient(project_root=tmp_path)

    async def _run() -> tuple[bool, bool, bool]:
        before = await c.is_ready()
        ok = await c.start()
        after = await c.is_ready()
        await c.stop()
        return before, ok, after

    before, ok, after = asyncio.run(_run())
    assert before is False
    assert ok is False
    assert after is False


def test_path_to_uri_for_real_file(tmp_path):
    """A real relative/absolute file path maps to a file:// URI."""
    f = tmp_path / "x.py"
    f.write_text("x = 1\n")
    uri = LspClient._path_to_uri(str(f))
    assert uri.startswith("file://")
    # round-trip back through the client's own decoder
    assert "x.py" in LspClient._uri_to_path(uri)
