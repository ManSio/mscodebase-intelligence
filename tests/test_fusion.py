"""Fusion arms: weights (shipped) / rrf / norm.

Frozen spec: `experiments/xerj_2026_11/fusion/frozen/PLAN.md` (E65).

The point of these tests is not that one formula is "right" — the A/B decides
that. It is that each arm really computes a different ranking, that the shipped
default is unchanged, and that policy (definition demotion) survives every arm.
"""

from __future__ import annotations

import pytest

from src.mcp.tools.investigate_tool import _merge


def _item(
    file: str,
    line: int = 1,
    channel: str = "graph",
    weight: float = 0.0,
    score: float = 0.0,
    defines: bool = False,
) -> dict:
    return {
        "file": file,
        "line": line,
        "score": score,
        "weight": weight,
        "defines": defines,
        "channels": {channel},
        "text": "",
        "symbol": "",
    }


def _order(rows: list[dict]) -> list[str]:
    return [row["file"] for row in rows]


# One row found by one heavy channel vs one row found by two light channels.
CONSENSUS_INPUT = [
    _item("src/heavy.py", channel="symbol", weight=2.5),
    _item("src/both.py", channel="graph", weight=1.0),
    _item("src/both.py", channel="grep", weight=1.7),
]


def test_default_arm_is_the_shipped_weight_formula(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_FUSION", raising=False)

    rows = _merge(CONSENSUS_INPUT, limit=5)

    assert _order(rows) == ["src/heavy.py", "src/both.py"]


def test_rrf_prefers_the_row_two_channels_found(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_FUSION", "rrf")

    rows = _merge(CONSENSUS_INPUT, limit=5)

    assert _order(rows) == ["src/both.py", "src/heavy.py"]
    assert rows[0]["channels"] == {"graph", "grep"}


def test_rrf_rank_is_the_reciprocal_of_the_channel_rank(monkeypatch):
    """The formula, not just the order: weight must not enter an RRF rank."""
    monkeypatch.setenv("MSCODEBASE_FUSION", "rrf")

    rows = _merge(
        [
            _item("src/heavy.py", channel="symbol", weight=2.5),
            _item("src/light.py", channel="graph", weight=0.3),
        ],
        limit=5,
    )

    assert rows[0]["rank"] == pytest.approx(round(1 / 60, 6), abs=1e-6)
    assert rows[1]["rank"] == pytest.approx(round(1 / 60, 6), abs=1e-6)


def test_rrf_drops_within_channel_position(monkeypatch):
    """Second hit of one channel scores 1/61, not 1/60."""
    monkeypatch.setenv("MSCODEBASE_FUSION", "rrf")

    rows = _merge(
        [
            _item("src/first.py", channel="search"),
            _item("src/second.py", channel="search"),
        ],
        limit=5,
    )

    assert [round(r["rank"], 6) for r in rows] == [0.016667, 0.016393]


def test_weights_arm_rank_is_score_plus_weight(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_FUSION", raising=False)

    rows = _merge(
        [_item("src/a.py", channel="search", weight=0.6, score=0.5)], limit=5
    )

    assert rows[0]["rank"] == pytest.approx(1.1)


def test_unknown_mode_falls_back_to_the_shipped_formula(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_FUSION", "nonsense")

    rows = _merge(CONSENSUS_INPUT, limit=5)

    assert _order(rows) == ["src/heavy.py", "src/both.py"]


def test_norm_trades_weight_for_the_channel_score(monkeypatch):
    items = [
        _item("src/heavy.py", channel="symbol", weight=2.5, score=0.0),
        _item("src/exact.py", channel="search", weight=0.3, score=1.0),
    ]

    monkeypatch.delenv("MSCODEBASE_FUSION", raising=False)
    assert _order(_merge(items, limit=5)) == ["src/heavy.py", "src/exact.py"]

    monkeypatch.setenv("MSCODEBASE_FUSION", "norm")
    assert _order(_merge(items, limit=5)) == ["src/exact.py", "src/heavy.py"]


def test_rrf_counts_a_channel_once_per_row(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_FUSION", "rrf")

    once = _merge([_item("src/a.py", channel="graph")], limit=5)
    twice = _merge(
        [_item("src/a.py", channel="graph"), _item("src/a.py", channel="graph")],
        limit=5,
    )

    assert twice[0]["rank"] == pytest.approx(once[0]["rank"])


def test_rrf_keeps_per_channel_ranks_under_interleaved_arrival(monkeypatch):
    """Channels run concurrently and append to one list.

    The counter is per channel, so interleaved arrival must not turn one
    channel's second hit into another channel's first — that would make the
    RRF arm non-deterministic between runs.
    """
    monkeypatch.setenv("MSCODEBASE_FUSION", "rrf")

    rows = _merge(
        [
            _item("src/g1.py", channel="graph"),
            _item("src/s1.py", channel="symbol"),
            _item("src/g2.py", channel="graph"),
        ],
        limit=5,
    )
    ranks = {row["file"]: round(row["rank"], 6) for row in rows}

    assert ranks["src/g1.py"] == 0.016667
    assert ranks["src/g2.py"] == 0.016393  # second graph hit, not first
    assert ranks["src/s1.py"] == 0.016667  # symbol's own first hit


def test_definition_demotion_holds_against_a_low_weight_neighbour(monkeypatch):
    """Review finding: a 0.25 cap let the definition lead in `norm`.

    On the `references` profile a symbol neighbour is 0.6, which is 0.12 after
    normalization — below the old cap.
    """
    items = [
        _item("src/defs.py", channel="definition", weight=2.5, defines=True),
        _item("src/neighbour.py", channel="symbol", weight=0.6),
    ]

    for arm in ("weights", "norm", "rrf"):
        monkeypatch.setenv("MSCODEBASE_FUSION", arm)
        rows = _merge(items, limit=5, demote_definitions=True)
        assert _order(rows)[0] == "src/neighbour.py", arm


def test_rrf_order_does_not_depend_on_arrival_order(monkeypatch):
    """Channels append concurrently; equal RRF ranks must not follow arrival."""
    monkeypatch.setenv("MSCODEBASE_FUSION", "rrf")

    a = _item("src/a.py", channel="graph")
    b = _item("src/b.py", channel="symbol")

    assert _order(_merge([a, b], limit=5)) == _order(_merge([b, a], limit=5))


def test_two_channels_on_one_row_count_twice(monkeypatch):
    """Frozen plan: RRF sums one term per ranking that found the row.

    `definition` and `symbol` are two different searches in `_symbols` (an exact
    definition lookup and a token-scored symbol search), so a row found by both
    has two terms — the round-2 review caught an earlier version that merged
    them into one and shifted the arm against its own spec.
    """
    monkeypatch.setenv("MSCODEBASE_FUSION", "rrf")

    rows = _merge(
        [
            _item("src/x.py", channel="definition"),
            _item("src/x.py", channel="symbol"),
        ],
        limit=5,
    )

    assert rows[0]["rank"] == pytest.approx(round(2 / 60, 6), abs=1e-6)


def test_definition_demotion_survives_every_arm(monkeypatch):
    items = [
        _item("src/defs.py", channel="definition", weight=2.5, defines=True),
        _item("src/caller.py", channel="grep", weight=1.7),
    ]

    for arm in ("weights", "norm", "rrf"):
        monkeypatch.setenv("MSCODEBASE_FUSION", arm)
        rows = _merge(items, limit=5, demote_definitions=True)
        assert _order(rows)[0] == "src/caller.py", arm


def test_definition_demotion_is_still_visible_in_rrf_scale(monkeypatch):
    """The cap must be scale-aware: 0.5 on an RRF rank (~0.017) is a no-op."""
    monkeypatch.setenv("MSCODEBASE_FUSION", "rrf")

    rows = _merge(
        [_item("src/defs.py", channel="definition", weight=2.5, defines=True)],
        limit=5,
        demote_definitions=True,
    )

    assert rows[0]["rank"] == pytest.approx(0.0)
