"""A score must describe the panel it claims to describe (E74 follow-up).

Two holes found by a reader in the published write-up, both reproduced before
the fix: `run.py` printed a table after executing zero tasks (`resuming:` was
only a line of text), and a capture row that was not in the panel raised the
denominator (`_stats` divides by `len(rows)`, and `rows` came from the file).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "experiments" / "bench_2026_11" / "capture.py"


def _capture_module():
    spec = importlib.util.spec_from_file_location("bench_capture_denominator", CAPTURE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PANEL = ["a1", "b2", "c3"]


def _rows(*ids: str) -> list[dict]:
    return [{"id": i, "tool_top5": False} for i in ids]


def test_zero_executed_is_refused_without_allow_replay() -> None:
    module = _capture_module()
    executed, resumed, refusal = module.check_capture_before_run(_rows(*PANEL), set(PANEL), PANEL)
    assert (executed, resumed) == (0, 3), "the counters are what the score must be read next to"
    assert refusal is not None, "a replay must not be scored as a run"
    assert "0 tasks executed" in refusal


def test_zero_executed_is_allowed_when_asked_for_explicitly() -> None:
    module = _capture_module()
    _, _, refusal = module.check_capture_before_run(
        _rows(*PANEL), set(PANEL), PANEL, allow_replay=True
    )
    assert refusal is None


def test_a_capture_row_outside_the_panel_is_refused() -> None:
    module = _capture_module()
    _, resumed, refusal = module.check_capture_before_run(
        _rows(*PANEL, "deadbeef"), set(PANEL), PANEL
    )
    assert resumed == 4, "four rows were read; the refusal must not silently filter them"
    assert refusal is not None, "a foreign row would inflate the denominator"
    assert "not in this panel" in refusal


def test_a_partial_resume_is_a_normal_run() -> None:
    module = _capture_module()
    executed, resumed, refusal = module.check_capture_before_run(_rows("a1"), {"a1"}, PANEL)
    assert (executed, resumed, refusal) == (2, 1, None)


def test_a_missing_row_after_the_run_is_refused() -> None:
    module = _capture_module()
    refusal = module.check_denominator_after_run(_rows("a1", "b2"), PANEL)
    assert refusal is not None, "a panel task without a row is a silent miss"
    assert "no row" in refusal


def test_a_complete_panel_passes() -> None:
    module = _capture_module()
    assert module.check_denominator_after_run(_rows(*PANEL), PANEL) is None
