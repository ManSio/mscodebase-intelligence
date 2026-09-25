"""Guard for the typed, actionable error envelope (2026-09-25)."""
import json

import pytest

from src.core.error_envelope import (
    ErrorCode,
    error_json,
    playbook,
    tool_error,
)


def test_every_code_has_a_concrete_next_action():
    for code in ErrorCode:
        hint = playbook(code)
        assert isinstance(hint, str) and len(hint) > 10, f"{code} has no hint"


def test_tool_error_shape_and_recovery_hint():
    err = tool_error(ErrorCode.NOT_FOUND, "no such symbol")
    d = err.to_dict()
    assert d["ok"] is False
    assert d["error"]["code"] == "NOT_FOUND"
    assert d["error"]["message"] == "no such symbol"
    assert "reindex" in d["error"]["next_action"].lower()


def test_error_json_is_valid_and_parsable():
    raw = error_json(ErrorCode.INDEX_NOT_READY, "0 chunks")
    parsed = json.loads(raw)
    assert parsed["ok"] is False
    assert parsed["error"]["code"] == "INDEX_NOT_READY"
    assert parsed["error"]["next_action"]


def test_detail_is_appended_to_hint():
    err = tool_error(ErrorCode.TIMEOUT, "exceeded 30s", detail="tool=search_code")
    assert "tool=search_code" in err.next_action


def test_details_pass_through():
    err = tool_error(ErrorCode.VALIDATION, "bad arg", details={"field": "query"})
    assert err.details == {"field": "query"}


def test_next_action_override():
    err = tool_error(ErrorCode.INTERNAL, "boom", next_action="Call support.")
    assert err.next_action == "Call support."


def test_unknown_code_raises():
    with pytest.raises(ValueError):
        tool_error("NOT_A_REAL_CODE", "x")
