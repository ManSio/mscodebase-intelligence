"""The suite lock must refuse a second run and free itself on release.

Two full suites on one checkout are what turned a <0.01s test into a 654s
report on 2026-11-14. The lock is a file lock, so the OS frees it if a run dies.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _conftest():
    spec = importlib.util.spec_from_file_location("mscb_conftest", ROOT / "tests" / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_second_acquire_fails_and_release_frees(tmp_path: Path) -> None:
    mod = _conftest()
    lock = tmp_path / "suite.lock"

    first = mod._acquire_file_lock(lock)
    assert first is not None
    try:
        assert mod._acquire_file_lock(lock) is None
    finally:
        mod._release_file_lock(first)

    second = mod._acquire_file_lock(lock)
    assert second is not None
    mod._release_file_lock(second)
