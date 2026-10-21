"""The red team as a repo test: every attack must be REFUSED, not survived.

The red team lives in tools/microtask_pipeline/red_team.py; this test runs it
and fails if any attack stops being defended. A guard that has never failed
has not been shown to be capable of failing (Tīrtha catalogue), so this test
is the continuous proof.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT / "tools" / "microtask_pipeline"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PIPELINE_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


red_team = _load("red_team")


def test_every_attack_is_defended():
    assert red_team.main() == 0


def test_red_team_covers_the_documented_attack_set():
    # the table in the README lists 13 attacks; the suite must not silently shrink
    assert len(red_team.RESULTS) == 13
