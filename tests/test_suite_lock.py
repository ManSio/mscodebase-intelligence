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


def test_lock_is_taken_in_the_controller_not_in_a_session_fixture():
    """Structural guard for the 2026-11-14 crash.

    A session-scoped fixture runs inside every xdist worker; the losers called
    pytest.exit(3) and CI reported `INTERNALERROR: worker crashed`. From inside
    the suite this is invisible (a nested run inherits the marker), so the shape
    is asserted: the lock lives in pytest_configure, workers skip via
    workerinput, and the per-worker fixture is gone.
    """
    source = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "def pytest_configure(config)" in source
    assert "def pytest_unconfigure(config)" in source
    assert 'getattr(config, "workerinput", None)' in source
    assert "_one_suite_per_tree" not in source
