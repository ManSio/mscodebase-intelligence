"""Guard: frozen experiment inputs must be committed, never kept in temp.

Regression guard for the 2026-09-26 incident: the E7/E11 frozen symptom list
lived in %TEMP%/opencode/e11 and was deleted, making verbatim regression
impossible. Any file under experiments/**/frozen/ must therefore be tracked
by git. Untracked frozen inputs fail CI.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _tracked() -> set[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
            text=True, encoding="utf-8",
        )
    except OSError:
        return set()
    if out.returncode != 0:
        return set()
    return {x for x in out.stdout.split("\0") if x}


def test_frozen_inputs_are_tracked() -> None:
    frozen_dir = REPO / "experiments"
    on_disk = [
        p for p in frozen_dir.rglob("frozen/*")
        if p.is_file()
    ]
    if not on_disk:
        return
    tracked = _tracked()
    if not tracked:
        pytest.skip("git not available")
    violations = [
        p.relative_to(REPO).as_posix()
        for p in on_disk
        if p.relative_to(REPO).as_posix() not in tracked
    ]
    assert not violations, (
        "frozen experiment inputs must be committed (not in %TEMP%):\n"
        + "\n".join(violations)
    )
