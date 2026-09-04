"""
Negative control + regression for issue #24.

check_commit_exists (scripts/verify_diary.py) must distinguish:
  - numeric run-ID / byte-count / Windows code  -> NOT a commit -> must NOT fail
    the ledger even though `git cat-file -t` finds no such object.
  - real numeric-lead commit (all-digit 7+ prefix) -> resolves via git -> True.
  - hex-with-letters missing commit -> git finds nothing -> False (warn as today).

The fix added one guard: after git finds no object, a purely-numeric token
(`isdigit()`) returns True (it is a run-ID/byte-count/Windows-code, not a
missing commit). It never rewrites the parser or _COMMIT_EXCLUDE.
"""

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_diary.py"
_spec = importlib.util.spec_from_file_location("verify_diary_under_test", _SCRIPT)
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)


class _FakeReturnCode:
    def __init__(self, returncode):
        self.returncode = returncode

    def communicate(self, timeout=30):
        pass


def _popen_returning(returncode):
    """Popen-заглушка: single attempt, заданный returncode."""

    def _fake_popen(*args, **kwargs):
        return _FakeReturnCode(returncode)

    return _fake_popen


def test_numeric_run_id_does_not_fail(monkeypatch):
    """Run-ID (11+ digits, no git object) must be treated as NOT a commit."""
    # Fake: git cat-file fails (returncode != 0) for any token.
    with mock.patch.object(verify.subprocess, "Popen", _popen_returning(1)):
        assert verify.check_commit_exists("33796959353") is True
        assert verify.check_commit_exists("2684354560") is True


def test_numeric_byte_count_does_not_fail(monkeypatch):
    """Byte-count (10 digits) also must not fail."""
    with mock.patch.object(verify.subprocess, "Popen", _popen_returning(1)):
        assert verify.check_commit_exists("2684354560") is True


def test_hex_missing_commit_still_warns(monkeypatch):
    """Hex-with-letters that git does NOT have must still be flagged (False)."""
    with mock.patch.object(verify.subprocess, "Popen", _popen_returning(1)):
        # Mimics a real short-hex that is not present in this repo.
        assert verify.check_commit_exists("f00baa1") is False


def test_real_numeric_commit_resolves(monkeypatch):
    """Numeric-lead commit present in repo -> git finds it -> True (guard not hit)."""
    with mock.patch.object(verify.subprocess, "Popen", _popen_returning(0)):
        # `3578642` is the real all-digit 7-prefix present in this repo.
        assert verify.check_commit_exists("3578642") is True


def test_mixed_hex_is_not_guard_bypassed_when_absent(monkeypatch):
    """Guard must NOT bypass mixed hex-with-letters that git rejects."""
    with mock.patch.object(verify.subprocess, "Popen", _popen_returning(1)):
        # Has letters -> isdigit() False -> still flagged as missing.
        assert verify.check_commit_exists("a1b2c3d") is False