"""Guard: our JSON error envelope must reach the client as `isError: true`.

The envelope is produced inside `error_boundary` as ordinary text, so MCP by
default reports a failed call as success (`isError=false`). `install_is_error_flag`
flips the flag in the low-level handler without touching the payload text.

These tests are the guard for the private FastMCP surface: if a future `mcp`
release changes `_mcp_server.request_handlers`, the install returns False and
this file fails instead of silently losing the flag.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from mcp.server.fastmcp import FastMCP

from mcp import types
from src.mcp.error_results import install_is_error_flag, is_error_envelope

ENVELOPE = json.dumps(
    {
        "ok": False,
        "error": {
            "code": "NOT_FOUND",
            "message": "no such symbol",
            "next_action": "Verify the identifier.",
            "details": {"tool": "probe"},
        },
    }
)


def _app(fn, name="probe") -> FastMCP:
    mcp = FastMCP("iserror-test")
    mcp.tool(name)(fn)
    assert install_is_error_flag(mcp) is True, "private FastMCP surface changed"
    return mcp


def _call(mcp: FastMCP, name: str = "probe", arguments: dict | None = None):
    handler = mcp._mcp_server.request_handlers[types.CallToolRequest]
    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name=name, arguments=arguments or {}),
    )
    return asyncio.run(handler(req))


def _text(result) -> str:
    return result.root.content[0].text


class TestIsErrorEnvelope:
    @pytest.mark.parametrize(
        "value",
        [
            ENVELOPE,
            '  {"ok": false, "error": {}}  ',
            '{"ok": false, "error": {"code": "X"}}',
        ],
    )
    def test_recognises_the_envelope(self, value):
        assert is_error_envelope(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "plain text",
            "{not json",
            '[{"ok": false}]',
            '{"ok": true, "data": 1}',
            '{"ok": false}',
            '{"ok": false, "error": "just a string"}',
            123,
            None,
        ],
    )
    def test_rejects_everything_else(self, value):
        assert is_error_envelope(value) is False


class TestProtocolFlag:
    def test_envelope_becomes_is_error(self):
        async def probe() -> str:
            return ENVELOPE

        result = _call(_app(probe))
        assert result.root.isError is True
        # payload must stay byte-identical so clients can json.loads() it
        assert json.loads(_text(result))["error"]["code"] == "NOT_FOUND"

    def test_success_text_stays_success(self):
        async def probe() -> str:
            return "✅ all good"

        result = _call(_app(probe))
        assert result.root.isError is False
        assert _text(result) == "✅ all good"

    def test_ok_json_stays_success(self):
        async def probe() -> str:
            return '{"ok": true, "data": [1, 2]}'

        result = _call(_app(probe))
        assert result.root.isError is False

    def test_dict_result_stays_success(self):
        async def probe() -> dict:
            return {"count": 3}

        result = _call(_app(probe))
        assert result.root.isError is False

    def test_raising_tool_still_reports_error(self):
        async def probe() -> str:
            raise ValueError("boom")

        result = _call(_app(probe))
        assert result.root.isError is True
        assert "boom" in _text(result)

    def test_arguments_are_still_validated(self):
        async def probe(query: str) -> str:
            return query

        mcp = _app(probe)
        result = _call(mcp, arguments={"query": "hello"})
        assert result.root.isError is False
        assert _text(result) == "hello"

    def test_install_is_idempotent(self):
        async def probe() -> str:
            return ENVELOPE

        mcp = _app(probe)
        assert install_is_error_flag(mcp) is True
        assert install_is_error_flag(mcp) is True
        result = _call(mcp)
        assert result.root.isError is True
        # exactly one wrap: text is not duplicated or prefixed
        assert _text(result) == ENVELOPE

    def test_real_error_boundary_output_is_flagged(self):
        """End-to-end through the real decorator, not a hand-made string."""
        from src.core.error_handler import ToolError, error_boundary

        @error_boundary("probe")
        async def probe() -> str:
            raise ToolError("controlled", detail="bad arg")

        result = _call(_app(probe))
        assert result.root.isError is True
        payload = json.loads(_text(result))
        assert payload["error"]["code"] == "INTERNAL_ERROR"
        assert payload["error"]["details"]["tool"] == "probe"
