"""E72: file-level dedup keeps a "which file" answer from repeating one file.

The flag is experimental and off by default; these tests pin both sides (the
shipped order must not move) and the reason the second pass exists (a "where is
X used" question with few files keeps all its rows).
"""

from __future__ import annotations

import pytest

from src.mcp.tools.investigate_tool import _dedup_by_file, _merge

ITEMS = [
    {"file": "a.py", "line": 1, "score": 3.0, "channels": ["search"]},
    {"file": "a.py", "line": 9, "score": 2.5, "channels": ["search"]},
    {"file": "a.py", "line": 20, "score": 2.4, "channels": ["grep"]},
    {"file": "b.py", "line": 5, "score": 2.0, "channels": ["search"]},
]


def _where(rows):
    return [(r["file"], r["line"]) for r in rows]


@pytest.fixture(autouse=True)
def _no_flag(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_FILE_DEDUP", raising=False)


def test_one_row_per_file_comes_first():
    head = [{"file": "a.py", "line": 1}, {"file": "b.py", "line": 5}]
    tail = [{"file": "a.py", "line": 9}, {"file": "a.py", "line": 20}]

    assert _where(_dedup_by_file(head + tail, 3)) == [
        ("a.py", 1),
        ("b.py", 5),
        ("a.py", 9),
    ]


def test_a_short_list_keeps_every_row():
    # "where is X used": three rows, two files - the second pass must not drop
    # the same-file call sites.
    rows = [{"file": "a.py", "line": 1}, {"file": "a.py", "line": 9},
            {"file": "b.py", "line": 5}]

    assert len(_dedup_by_file(rows, 8)) == 3


def test_flag_off_keeps_the_shipped_order():
    assert _where(_merge(ITEMS, 3)) == [("a.py", 1), ("a.py", 9), ("a.py", 20)]


def test_flag_on_leads_with_files(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_FILE_DEDUP", "file")

    assert _where(_merge(ITEMS, 3)) == [("a.py", 1), ("b.py", 5), ("a.py", 9)]


def test_unknown_value_is_off(monkeypatch):
    # A typo in an env var must never silently change the shipped answer.
    monkeypatch.setenv("MSCODEBASE_FILE_DEDUP", "files")

    assert _where(_merge(ITEMS, 3)) == [("a.py", 1), ("a.py", 9), ("a.py", 20)]
