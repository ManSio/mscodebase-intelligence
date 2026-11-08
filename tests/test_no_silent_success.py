"""Conformance: a response may not look successful when nothing was established.

Why this file exists (XERJ 2026-11 E3): four failure shapes are the same bug in
different clothes — the caller cannot tell "measured and empty" from "present and
wrong". Each test below asserts the shape is *visible* in the answer:

A. empty population      -> a gate refuses (exit 2), it does not print "0".
B. unavailable dependency -> the answer names the degraded channel.
C. a number is measured  -> latency comes from a clock, not from a constant.
D. agreement is not proof -> two non-exact channels returning the same place is
   still "no exact match", not a confirmed answer.

D is the one our own `investigate` used to get wrong: the semantic and symbol
channels always return neighbours, so "where is <absent symbol> implemented"
produced eight confident-looking `file:line` rows and no warning.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"_probe_{name.replace('.', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _format(**kwargs):
    from src.mcp.tools.investigate_tool import InvestigateTool

    tool = object.__new__(InvestigateTool)  # _format touches no instance state
    params = {
        "query": "where is ghost_symbol implemented",
        "identifiers": ["ghost_symbol", "implemented"],
        "merged": [],
        "symbol_lines": [],
        "degraded": [],
        "exact": {"per": {"ghost_symbol": 0}},
    }
    params.update(kwargs)
    return InvestigateTool._format(tool, **params)


# ── A. empty population ──────────────────────────────────────────────────────

def test_empty_population_refuses_instead_of_reporting_zero():
    gate = _load_script("check_write_bytes.py")
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = gate.main([])
    assert code == 2, f"empty input must be a refusal, got exit {code}"
    assert err.getvalue().strip(), "a refusal must say why (stderr), not stay silent"
    assert "0 violation" not in out.getvalue().lower()


# ── B/D. degraded channel and agreement are not evidence ─────────────────────

def test_degraded_channel_is_named_in_the_answer():
    text = _format(degraded=["grep:timeout"])
    assert "degraded: grep:timeout" in text


def test_degraded_grep_makes_no_exact_claim_either_way():
    """Silence is not zero (T10 at the answer level).

    When the channel that establishes exact matches did not run, the answer
    must neither claim hits nor claim "0 hits" — both would be inventions.
    """
    text = _format(degraded=["grep:timeout"], exact={"per": {}})
    assert "exact:" not in text


def test_no_exact_hits_says_the_results_are_neighbours():
    text = _format(
        merged=[
            {"file": "src/core/search/cypher_sql.py", "line": 278,
             "text": "NotImplementedError — function", "channels": {"search"}},
        ],
        exact={"per": {"ghost_symbol": 0, "implemented": 5}},
    )
    assert "⚠️ exact: ghost_symbol=0" in text
    assert "neighbours" in text


def test_agreement_between_non_exact_channels_is_not_confirmation():
    """Two channels naming the same place is correlation, not proof."""
    same_file = "src/core/search/cypher_sql.py"
    text = _format(
        merged=[
            {"file": same_file, "line": 278, "text": "a", "channels": {"search", "symbol"}},
            {"file": same_file, "line": 300, "text": "b", "channels": {"search", "symbol"}},
        ],
        exact={"per": {"ghost_symbol": 0}},
    )
    assert "⚠️ exact: ghost_symbol=0" in text
    assert "neighbours" in text


def test_exact_hits_are_reported_without_the_warning():
    text = _format(exact={"per": {"build_call_graph": 30}})
    assert "exact: build_call_graph=30" in text
    assert "⚠️" not in text.split("exact:")[0].split("\n")[-1] + ""


# ── C. the number is measured, not pasted ────────────────────────────────────

def test_latency_comes_from_a_clock():
    from src.core.error_handler import error_boundary

    @error_boundary("probe")
    def slow_failure():
        time.sleep(0.06)
        raise RuntimeError("boom")

    payload = slow_failure()
    import json

    envelope = json.loads(payload) if isinstance(payload, str) else payload
    assert envelope["ok"] is False
    latency = envelope["error"]["details"]["latency_ms"]
    assert latency >= 50, f"60 ms call reported {latency} ms — measurement is fake"


def test_zero_latency_is_not_printed_for_a_measured_call():
    """A placeholder is a constant; two different costs must differ."""
    import json

    from src.core.error_handler import error_boundary

    def measure(sleep_s: float) -> int:
        @error_boundary("probe")
        def failing():
            time.sleep(sleep_s)
            raise RuntimeError("boom")

        payload = failing()
        envelope = json.loads(payload) if isinstance(payload, str) else payload
        return envelope["error"]["details"]["latency_ms"]

    fast, slow = measure(0.01), measure(0.08)
    assert slow > fast, f"latency does not track real cost: {fast} vs {slow}"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
