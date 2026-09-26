"""Typed, actionable error envelope for MCP tools.

Every tool failure should carry a stable ``code``, a human ``message``, and a
``next_action`` hint so an agent can branch and recover without guessing
(research 2026-09-25: Orisu/Perplexity/xAI MCP envelopes, GitHub error style
guide, LiveMCP-101 failure taxonomy).

Shape::

    {"ok": false, "error": {"code": "...", "message": "...",
                            "next_action": "...", "details": {...}}}

Dependency-free (stdlib only) so any layer can import it without cycles.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

__all__ = ["ErrorCode", "ToolError", "tool_error", "error_json", "playbook"]


class ErrorCode(str, Enum):
    VALIDATION = "VALIDATION_FAILED"
    NOT_FOUND = "NOT_FOUND"
    AUTH = "AUTH_REQUIRED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    INDEX_NOT_READY = "INDEX_NOT_READY"
    REINDEX_IN_PROGRESS = "REINDEX_IN_PROGRESS"
    DEPENDENCY_DOWN = "DEPENDENCY_DOWN"
    CONFLICT = "CONFLICT"
    INTERNAL = "INTERNAL_ERROR"


# The "what to do about it" for each code. Agents branch on `code`; humans read
# `next_action`. Keep each hint concrete and single-step.
_PLAYBOOK: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION: "Fix the arguments and retry.",
    ErrorCode.NOT_FOUND: (
        "Verify the identifier. If the file is new/unchanged index is stale, "
        "call intel_trigger_reindex(mode='incremental') and retry after completion."
    ),
    ErrorCode.AUTH: (
        "Set/refresh the credential in .env and restart the MCP. Do NOT blind-retry."
    ),
    ErrorCode.TIMEOUT: (
        "Bounded operation exceeded its limit. Retry once; if it repeats, reduce "
        "scope (fewer files / smaller limit) or raise the relevant *_TIMEOUT env."
    ),
    ErrorCode.RATE_LIMIT: "Back off; the server already retries with backoff.",
    ErrorCode.INDEX_NOT_READY: (
        "Index is empty or building. Call intel_trigger_reindex(mode='incremental') "
        "and poll intel_get_job_status until 'completed'."
    ),
    ErrorCode.REINDEX_IN_PROGRESS: (
        "A reindex is running; searches fast-fail by design. Poll "
        "intel_get_job_status(job_id) and retry when it completes."
    ),
    ErrorCode.DEPENDENCY_DOWN: (
        "Embedder/reranker unavailable. The server auto-revives it; retry in a "
        "few seconds (first revive can take ~18s)."
    ),
    ErrorCode.CONFLICT: "Re-read the latest state, reconcile, and retry.",
    ErrorCode.INTERNAL: (
        "Retry once. If it persists, call get_logs and report details.request_id."
    ),
}


@dataclass
class ToolError:
    code: str
    message: str
    next_action: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ok": False, "error": asdict(self)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def playbook(code: ErrorCode | str) -> str:
    """Return the canonical next_action for a code (raises on unknown)."""
    if not isinstance(code, ErrorCode):
        code = ErrorCode(code)
    return _PLAYBOOK[code]


def tool_error(
    code: ErrorCode | str,
    message: str,
    *,
    detail: str = "",
    details: Optional[dict] = None,
    next_action: Optional[str] = None,
) -> ToolError:
    """Build a typed, actionable error.

    Args:
        code: one of ErrorCode (or its value).
        message: human-readable cause.
        detail: extra context appended to the playbook hint.
        details: machine-readable extras (tool, missing, present, ...).
        next_action: override the playbook hint (use sparingly).
    """
    if not isinstance(code, ErrorCode):
        code = ErrorCode(code)  # raises ValueError on unknown code
    hint = next_action if next_action is not None else _PLAYBOOK[code]
    if detail:
        hint = f"{hint} ({detail})"
    return ToolError(code=code.value, message=message, next_action=hint,
                     details=details or {})


def error_json(code: ErrorCode | str, message: str, **kwargs: Any) -> str:
    """Convenience: ``tool_error(...).to_json()``."""
    return tool_error(code, message, **kwargs).to_json()
