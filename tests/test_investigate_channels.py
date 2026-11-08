"""Guard: the semantic channel must reach the merged answer.

Measured 2026-11-08 (E1): `search` delivered 0 hits across 24 `investigate`
answers while symbol/grep/graph/impact delivered 129. Cause was a key mismatch,
not a weak channel — the searcher returns `{text, metadata, final_score}` with
the path inside `metadata`, and `_merge` drops items whose `file` is empty. The
failure was silent: no `degraded` entry, just a shorter list.
"""
from __future__ import annotations

from src.mcp.tools.investigate_tool import (
    _asks_for_callers,
    _merge,
    _relpath,
    _search_row_to_item,
)


def test_metadata_row_becomes_a_merge_item():
    row = {
        "text": "FILE: src/core/indexing/freshness.py\n...",
        "metadata": {"file": "src/core/indexing/freshness.py", "start_line": 56},
        "final_score": 0.79,
        "source": "sqlite",
    }
    item = _search_row_to_item(row, 0)
    assert item["file"] == "src/core/indexing/freshness.py"
    assert item["line"] == 56
    assert item["score"] == 1.0  # rank-based, not the raw final_score
    assert item["channels"] == {"search"}

    merged = _merge([item], limit=8)
    assert merged and merged[0]["file"] == "src/core/indexing/freshness.py"


def test_flat_row_still_works():
    """A searcher change that flattens the row must not break the merge."""
    item = _search_row_to_item(
        {"file_path": "src/a.py", "line": 3, "text": "x", "score": 0.5}, 1
    )
    assert (item["file"], item["line"]) == ("src/a.py", 3)


def test_row_without_any_path_is_dropped_not_invented():
    item = _search_row_to_item({"text": "no path here"}, 2)
    assert item["file"] is None
    assert _merge([item], limit=8) == []


def test_metadata_that_is_not_a_dict_is_ignored():
    item = _search_row_to_item({"file_path": "src/b.py", "line": 1, "metadata": "junk"}, 0)
    assert item["file"] == "src/b.py"


# ── path shapes: one location must stay one row ─────────────────────────────

def test_absolute_and_relative_paths_are_one_location():
    """Measured 2026-11-08: the same line appeared twice, wasting a slot."""
    root = r"D:\Project\MSCodeBase"
    items = [
        {"file": "src/core/x.py", "line": 11, "text": "a", "score": 0.2,
         "weight": 0.3, "channels": {"grep"}},
        {"file": r"D:\Project\MSCodeBase\src\core\x.py", "line": 11, "text": "b",
         "score": 0.0, "weight": 1.2, "channels": {"symbol"}},
    ]
    merged = _merge(items, limit=8, root=root)
    assert len(merged) == 1, merged
    assert merged[0]["file"] == "src/core/x.py"
    assert merged[0]["channels"] == {"grep", "symbol"}
    assert merged[0]["rank"] == 1.2


def test_definition_outranks_a_high_raw_search_score():
    """Measured 2026-11-08: final_score 10.32 vs definition weight 2.5 put the
    definition 7th. The search score is rank-based now, so it cannot."""
    search = _search_row_to_item(
        {"metadata": {"file": "src/a.py", "start_line": 1}, "final_score": 10.32}, 0
    )
    definition = {
        "file": "src/b.py", "line": 4, "text": "X — class_definition",
        "score": 0.0, "weight": 2.5, "defines": True, "channels": {"definition"},
    }
    merged = _merge([search, definition], limit=8, root=None)
    assert merged[0]["file"] == "src/b.py"
    assert search["score"] == 1.0


def test_caller_question_demotes_the_definition_but_keeps_it():
    definition = {
        "file": "src/b.py", "line": 4, "text": "X — class_definition",
        "score": 0.0, "weight": 2.5, "defines": True, "channels": {"definition"},
    }
    caller = {
        "file": "src/c.py", "line": 9, "text": "caller of X",
        "score": 0.0, "weight": 1.6, "channels": {"graph"},
    }
    merged = _merge([definition, caller], limit=8, root=None, demote_definitions=True)
    assert [r["file"] for r in merged] == ["src/c.py", "src/b.py"]


def test_relpath_leaves_foreign_and_pseudo_paths_alone():
    assert _relpath("(memory)", r"D:\p") == "(memory)"
    assert _relpath("/elsewhere/x.py", r"D:\p") == "/elsewhere/x.py"
    assert _relpath("", r"D:\p") == ""
    assert _relpath(r"D:\p\a\b.py", r"D:\p") == "a/b.py"


# ── intent: "who calls" must not lead with the definition ───────────────────

def test_callers_markers_are_recognised():
    for query in ("Who calls `want_bytes`?", "who uses this",
                  "list callers of foo", "кто вызывает foo"):
        assert _asks_for_callers(query), query


def test_definition_questions_are_not_callers():
    for query in ("Where is `Signer` defined?", "Где определяется build_call_graph?",
                  "what does func do"):
        assert not _asks_for_callers(query), query

