"""Protocol-level flag for our JSON error envelope (MCP boundary).

`error_boundary` returns the envelope
``{"ok": false, "error": {"code", "message", "next_action", "details"}}``
as ordinary text, so MCP reports ``isError = false`` and an agent that branches
on the protocol flag sees a failed call as successful. This module flips the
flag at the single boundary where the result leaves the server.

Why not raise: FastMCP's ``Tool.run`` wraps every exception into
``ToolError("Error executing tool <name>: ...")``, which would prefix the
envelope and break machine parsing. The low-level handler is the only place
that can set the flag while leaving the payload byte-identical.

Cost: the handler is a private FastMCP surface (``mcp._mcp_server``,
``server.request_handlers``). It is pinned by ``mcp==1.30.0`` and guarded by
``tests/test_mcp_is_error.py`` — if the surface changes, the guard fails loudly
instead of silently returning ``isError=false`` again.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("mscodebase_server.error_results")

__all__ = ["is_error_envelope", "install_is_error_flag"]


def is_error_envelope(value: Any) -> bool:
    """True if ``value`` is exactly our error envelope (not any JSON)."""
    if not isinstance(value, str):
        return False
    text = value.lstrip()
    if not text.startswith("{"):
        return False
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(parsed, dict)
        and parsed.get("ok") is False
        and isinstance(parsed.get("error"), dict)
    )


def _mark_error(result: Any, types: Any) -> None:
    """Flip ``isError`` on a ServerResult holding a CallToolResult (in place)."""
    payload = getattr(result, "root", None)
    if not isinstance(payload, types.CallToolResult) or payload.isError:
        return
    texts = [c.text for c in payload.content if isinstance(c, types.TextContent)]
    if len(texts) != 1 or not is_error_envelope(texts[0]):
        return
    try:
        payload.isError = True
    except (TypeError, ValueError):  # pragma: no cover - frozen model some day
        result.root = types.CallToolResult(
            content=payload.content,
            structuredContent=payload.structuredContent,
            isError=True,
        )


def install_is_error_flag(mcp) -> bool:
    """Wrap the low-level CallTool handler so envelopes surface as errors.

    Idempotent: calling it twice does not double-wrap. Returns False (and
    logs) when the private surface is not available — the server keeps working,
    only the protocol flag stays false.
    """
    from mcp import types

    server = getattr(mcp, "_mcp_server", None)
    if server is None or not hasattr(server, "request_handlers"):
        logger.warning(
            "isError flag not installed: FastMCP private surface changed "
            "(mcp._mcp_server.request_handlers missing)"
        )
        return False

    key = types.CallToolRequest
    original = server.request_handlers.get(key)
    if original is None:
        logger.warning("isError flag not installed: no CallToolRequest handler yet")
        return False
    if getattr(original, "_mscodebase_is_error", False):
        return True

    async def handler(req):
        result = await original(req)
        try:
            _mark_error(result, types)
        except Exception:  # noqa: BLE001 - never break a tool call on a marker
            logger.debug("isError flag: failed to inspect result", exc_info=True)
        return result

    handler._mscodebase_is_error = True  # type: ignore[attr-defined]
    server.request_handlers[key] = handler
    logger.info("✅ isError flag installed (JSON error envelope -> isError=true)")
    return True
