"""Wire-level guard: `error_envelope` is the MCP error contract (2026-11-08).

Breaking change decided by the owner: a failed tool call returns
``{"ok": false, "error": {"code", "message", "next_action", "details"}}``
as JSON text instead of the old Markdown block.

These tests are the negative control for the change: a success payload must NOT
become an envelope, and an error payload must NOT survive as "✅ Completed"
(the defect that existed before: 69 `{"status": "error"}` dicts were rendered
with a green checkmark).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from src.core.error_handler import (
    IndexNotReadyError,
    RateLimitError,
    ToolError,
    _format_error_response,
    _format_success_response,
    error_boundary,
)


def _envelope(raw: str) -> dict:
    parsed = json.loads(raw)
    assert set(parsed) == {"ok", "error"}, parsed
    assert parsed["ok"] is False
    err = parsed["error"]
    assert set(err) == {"code", "message", "next_action", "details"}
    assert err["next_action"], "every error must carry an actionable hint"
    return err


class TestExceptionPath:
    def test_controlled_tool_error(self):
        @error_boundary("probe")
        async def boom():
            raise ToolError("controlled", detail="bad arg")

        err = _envelope(asyncio.run(boom()))
        assert err["code"] == "INTERNAL_ERROR"
        assert err["message"] == "controlled"
        assert err["details"]["tool"] == "probe"
        assert err["details"]["detail"] == "bad arg"
        assert err["details"]["status"] == "error"

    def test_index_not_ready_has_recovery_hint(self):
        @error_boundary("probe")
        async def not_ready():
            raise IndexNotReadyError()

        err = _envelope(asyncio.run(not_ready()))
        assert err["code"] == "INDEX_NOT_READY"
        assert "reindex" in err["next_action"].lower()

    def test_rate_limit(self):
        @error_boundary("probe")
        async def limited():
            raise RateLimitError(detail="too fast")

        err = _envelope(asyncio.run(limited()))
        assert err["code"] == "RATE_LIMIT"
        assert err["details"]["detail"] == "too fast"

    def test_timeout(self):
        @error_boundary("probe", timeout_ms=20)
        async def slow():
            await asyncio.sleep(5)

        err = _envelope(asyncio.run(slow()))
        assert err["code"] == "TIMEOUT"
        assert err["details"]["latency_ms"] >= 0

    def test_unexpected_exception_is_internal(self):
        @error_boundary("probe")
        async def crash():
            raise ValueError("boom")

        err = _envelope(asyncio.run(crash()))
        assert err["code"] == "INTERNAL_ERROR"
        assert "boom" in err["message"]

    def test_sync_wrapper(self):
        @error_boundary("probe")
        def crash():
            raise RuntimeError("sync boom")

        err = _envelope(crash())
        assert err["code"] == "INTERNAL_ERROR"
        assert "sync boom" in err["message"]


class TestDictionaryPath:
    """Tools return {"status": "error"} dicts instead of raising — 69 sites."""

    def test_error_dict_is_not_a_green_checkmark(self):
        raw = _format_success_response(
            {"status": "error", "message": "Path does not exist: Z:/nope"}, 7
        )
        assert "\u2705" not in raw, "an error result must never look successful"
        err = _envelope(raw)
        assert err["message"] == "Path does not exist: Z:/nope"
        assert err["details"]["latency_ms"] == 7

    @pytest.mark.parametrize("status", ["error", "warning", "denied", "too_large", "not_installed"])
    def test_error_like_statuses_are_envelopes(self, status):
        err = _envelope(_format_success_response({"status": status, "message": "x"}, 1))
        assert err["details"]["status"] == status

    def test_success_dict_stays_a_success(self):
        raw = _format_success_response({"status": "ok", "count": 3}, 5)
        assert raw.startswith("\u2705")
        assert "ok" not in raw or "ok:" in raw

    def test_degraded_fallback_stays_a_success(self):
        raw = _format_success_response({"status": "fallback", "count": 1}, 2)
        assert not raw.startswith("{"), "fallback is degraded success, not an error"

    def test_code_from_payload_is_respected(self):
        err = _envelope(
            _format_success_response(
                {"status": "error", "code": "NOT_FOUND", "message": "gone"}, 3
            )
        )
        assert err["code"] == "NOT_FOUND"

    def test_already_wrapped_envelope_passes_through(self):
        original = json.dumps({"ok": False, "error": {"code": "TIMEOUT",
                                                      "message": "m",
                                                      "next_action": "n",
                                                      "details": {}}})
        assert _format_success_response(json.loads(original), 1) == original


class TestErrorResponseShape:
    def test_details_keep_legacy_fields(self):
        err = _envelope(
            _format_error_response(
                "timeout",
                "Operation timed out after 100ms",
                detail="Attempts: 1/1",
                recovery_hint="Reduce scope",
                latency_ms=103,
                tool="search_code",
                recoverable=False,
            )
        )
        assert err["code"] == "TIMEOUT"
        assert err["details"] == {
            "status": "timeout",
            "recoverable": False,
            "tool": "search_code",
            "detail": "Attempts: 1/1",
            "latency_ms": 103,
        }
        assert err["next_action"] == "Reduce scope"
