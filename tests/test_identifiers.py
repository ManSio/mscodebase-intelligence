"""Identifiers extracted from a question must not be hashes or commit trailers.

E71, discovered by the external benchmark: a Gerrit `Change-Id` took the first
slot in `_identifiers`, the gate counted it as "0 occurrences", and every
sqlalchemy commit abstained (0/40 at hit@5).
"""

from __future__ import annotations

from src.mcp.tools.investigate_tool import _identifiers

GERRIT_MESSAGE = (
    "discard pooled connection when its close is interrupted\n\n"
    "Fixed issue where a task was cancelled while closing.\n\n"
    "Fixes: #13673\n"
    "Change-Id: Iaf8be4a9f4cc0f4435ae97ef8d961ce89375ffcc\n"
)


def test_gerrit_change_id_is_not_an_identifier():
    ids = _identifiers(GERRIT_MESSAGE)

    assert not any(len(i) >= 32 for i in ids), ids
    assert "Iaf8be4a9f4cc0f4435ae97ef8d961ce89375ffcc" not in ids


def test_commit_trailers_are_not_identifiers():
    ids = [i.lower() for i in _identifiers(GERRIT_MESSAGE)]

    for word in ("fixed", "fixes", "issue", "issues", "closes", "resolves"):
        assert word not in ids, ids


def test_a_real_method_name_still_survives():
    ids = _identifiers("where is _ConnectionRecord.__close defined")

    assert ids == ["_ConnectionRecord.__close"]


def test_close_is_still_an_identifier():
    # Left out of the stopword list on purpose: `close` is a real method name.
    assert "close" in _identifiers("where is close defined")


def test_a_plain_question_still_yields_its_identifier():
    assert _identifiers("where is get_progress_file defined") == ["get_progress_file"]
