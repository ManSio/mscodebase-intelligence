"""Guard: the frozen-list novelty gate (G6) must be able to both flag and pass.

Regression for the 2026-09-26 F4b finding: the v1 gate was blind to a probe
that is a morphological twin of a catalogue arrival phrase (F4b item #3). A
gate that cannot fail is useless, so this test runs the executable negative
control (`--selftest`) plus a real end-to-end check on the F4b handout.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "frozen_overlap_check.py"
F4B_SYMPTOM = REPO / "experiments" / "4A_unit_of_return" / "frozen" / "f4b" / "handout_symptom.md"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_selftest_has_both_controls() -> None:
    """Negative (twin flagged) + positive (unrelated clean) must both hold."""
    if not SCRIPT.exists():
        pytest.skip("frozen_overlap_check.py missing")
    p = _run("--selftest")
    assert p.returncode == 0, f"selftest failed:\n{p.stdout}\n{p.stderr}"
    assert "SELFTEST OK" in p.stdout


def test_gate_flags_the_known_f4b_twin() -> None:
    """The gate must now FAIL on F4b handout (item #3 = twin of arrival phrase).

    If this ever PASSES again, the gate regressed to its blind v1 behaviour.
    """
    if not F4B_SYMPTOM.exists():
        pytest.skip("F4b handout missing")
    p = _run(str(F4B_SYMPTOM))
    assert p.returncode == 1, f"expected FAIL, got rc={p.returncode}:\n{p.stdout}"
    assert "OVERLAP: FAIL" in p.stdout
    assert "timing out" in p.stdout and "times out" in p.stdout
