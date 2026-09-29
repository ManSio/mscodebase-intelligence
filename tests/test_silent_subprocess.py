#!/usr/bin/env python3
"""silent_subprocess STARTUPINFO guards (2026-09-28).

Regression S1: `subprocess.STARTUPINFO()` ctor must live INSIDE the narrowed
try in `_silent_startupinfo` — on an exotic win32 build without STARTUPINFO,
`apply()` + wrapper use must not raise (missing ctor -> startupinfo=None,
which Popen accepts as default). S2: the `_SilentPopen` setdefault must be
wrapped exactly like the `_with_flags` one (except AttributeError/OSError/
TypeError).

Positive control: with STARTUPINFO present, the wrappers still inject a real
`startupinfo` object into the underlying call.

Note: root conftest replaces subprocess.Popen with a plain function during
tests (_no_console_windows) — these tests install their own dummy Popen
CLASS so apply()'s subclassing is exercised faithfully without spawning.
"""

import subprocess
import sys

import pytest

import src.core.silent_subprocess as mod

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="silent_subprocess is win32-only")


class _DummyPopen:
    """Stand-in Popen class: records kwargs, spawns nothing."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


@pytest.fixture
def isolated_apply(monkeypatch):
    """Dummy Popen class + save/restore the four patched attrs and _APPLIED."""
    monkeypatch.setattr(subprocess, "Popen", _DummyPopen)
    for name in ("run", "check_output", "check_call"):
        monkeypatch.setattr(subprocess, name, getattr(subprocess, name))
    monkeypatch.setattr(mod, "_APPLIED", False)
    return monkeypatch


def test_apply_and_popen_no_raise_without_startupinfo(isolated_apply, monkeypatch):
    """S1+S2: missing subprocess.STARTUPINFO -> apply() and use must not raise."""
    monkeypatch.delattr(subprocess, "STARTUPINFO", raising=False)
    assert not hasattr(subprocess, "STARTUPINFO")
    mod.apply()  # must not raise
    inst = subprocess.Popen(["echo", "hi"])  # S2 path: must not raise either
    assert isinstance(inst, _DummyPopen)
    assert inst.kwargs.get("startupinfo") is None


def test_popen_injects_startupinfo_when_present(isolated_apply):
    """Positive control (Popen path): real startupinfo object is injected."""
    assert hasattr(subprocess, "STARTUPINFO"), "positive control needs STARTUPINFO"
    mod.apply()
    inst = subprocess.Popen(["echo", "hi"])
    assert inst.kwargs.get("startupinfo") is not None
    assert inst.kwargs.get("creationflags") == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_run_wrapper_injects_startupinfo_when_present(isolated_apply, monkeypatch):
    """Positive control (run path): _with_flags still passes startupinfo."""
    calls = {}

    def fake_run(*args, **kwargs):
        calls.update(kwargs)

        class _R:
            returncode = 0

        return _R()

    assert hasattr(subprocess, "STARTUPINFO"), "positive control needs STARTUPINFO"
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_APPLIED", False)
    mod.apply()
    subprocess.run(["echo", "hi"])
    assert calls.get("startupinfo") is not None
