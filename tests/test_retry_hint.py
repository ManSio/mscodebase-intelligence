"""Retry hint (option C, E69): an abstain that names the next call.

Frozen: `experiments/retry_hint_2026_11/frozen/PLAN.md`.
"""

from __future__ import annotations

import asyncio
import json

from src.mcp.tools.investigate_tool import _retry_hint, _rewrite_hint


def test_retry_hint_names_the_parameter_and_the_limit():
    hint = _retry_hint("where is x", 8, 8)

    assert "Neighbours withheld: 8 (unverified)." in hint
    assert "include_neighbours=true" in hint
    assert "limit=8" in hint
    assert hint.startswith("\nnext: investigate(") or "\nnext: investigate(" in hint


def test_retry_hint_round_trips_the_query_verbatim():
    query = 'где "прогресс" и \\ бэкслеш'
    hint = _retry_hint(query, 3, 5)

    line = next(x for x in hint.splitlines() if x.startswith("next:"))
    call = line[len("next: investigate("):-1]
    args = dict(
        part.split("=", 1) for part in call.split(", ")
    )
    assert json.loads(args["query"]) == query
    assert args["include_neighbours"] == "true"


def test_rewrite_hint_has_the_hints_placeholder():
    hint = _rewrite_hint("где вычисляется путь")

    assert 'hints=["<identifier>"]' in hint
    assert "next: investigate(" in hint


def test_rewrite_gate_prints_the_machine_readable_next_line(tmp_path, monkeypatch):
    from tests.test_investigate import _fake_tool

    monkeypatch.setenv("MSCODEBASE_ASK_REWRITE", "1")
    tool = _fake_tool(tmp_path)

    out = asyncio.run(
        tool.execute("где вычисляется путь прогресса", project_root=str(tmp_path))
    )

    assert "verdict: ask_rewrite" in out
    assert "next: investigate(" in out
    assert 'hints=["<identifier>"]' in out
