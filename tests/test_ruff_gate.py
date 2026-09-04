"""Negative control + guard-тест ruff_gate.py (scripts/ruff_gate.py).

Проверяет:
1. Happy path: ruff чист → exit 0.
2. Fail path: ruff находит ошибку → exit 1.
3. No-ruff path: ruff не установлен → advisory skip, exit 0.

Guard защищает от повторения CI lint red (5a771789/b121ab19/3dd79ba2).
"""
import importlib.util
import subprocess
from pathlib import Path
from unittest import mock

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ruff_gate.py"
_spec = importlib.util.spec_from_file_location("ruff_gate_under_test", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class _FakeProc:
    def __init__(self, rc: int, stdout: str = ""):
        self.returncode = rc
        self._stdout = stdout

    def communicate(self, timeout: int = 300):
        return self._stdout, ""


def test_happy_path(monkeypatch):
    """ruff clean -> exit 0."""
    with mock.patch.object(subprocess, "Popen", return_value=_FakeProc(0)):
        with mock.patch.dict("sys.modules", {"ruff": object()}):
            assert mod.main() == 0


def test_fail_path(monkeypatch):
    """ruff lint error -> exit 1."""
    err_output = "E501 line too long"
    with mock.patch.object(subprocess, "Popen", return_value=_FakeProc(1, err_output)):
        with mock.patch.dict("sys.modules", {"ruff": object()}):
            assert mod.main() == 1


def test_no_ruff_returns_zero():
    """ruff not installed -> advisory skip, exit 0 (does not block commit)."""
    import sys
    real_modules = {k: v for k, v in sys.modules.items() if k != "ruff"}
    with mock.patch.dict("sys.modules", real_modules, clear=True):
        with mock.patch("builtins.__import__", side_effect=ImportError("no ruff")):
            assert mod.main() == 0
