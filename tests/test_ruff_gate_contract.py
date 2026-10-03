"""The ruff gate must be able to FAIL, and must be able to say why.

Two defects closed here, both found on 2026-10-03:
  1. it invoked `python -m ruff`, which in this venv prints nothing and exits 1
     (the installed `ruff` has no `__main__`) — the gate was permanently red and
     mute, which reads as "lint is broken", not "the runner is broken";
  2. a non-zero exit with no output produced the bare line "exit 1" and nothing
     else, so the failure was indistinguishable from a lint error.

A gate that cannot fail is worse than no gate, and a gate that fails for an
unexplained reason gets disabled within a week. Both are pinned here.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("ruff_gate", ROOT / "scripts" / "ruff_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Stub:
    def __init__(self, rc, out=""):
        self.returncode = rc
        self._out = out
        self.killed = False

    def communicate(self, timeout=None):
        return self._out, None


def test_resolved_ruff_actually_runs():
    """Guards the module-form regression: the resolver must return a live tool."""
    mod = _load()
    cmd = mod.ruff_cmd()
    assert cmd is not None, "no working ruff found by any resolution path"
    probe = subprocess.run([*cmd[: cmd.index("check")], "--version"], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=60)
    assert probe.returncode == 0 and "ruff" in probe.stdout.lower()


def test_module_form_is_not_used_when_it_is_dead(monkeypatch):
    """`python -m ruff` here exits 1 with no output; it must not be selected."""
    mod = _load()
    monkeypatch.setattr(mod.shutil, "which", lambda _n: None)
    monkeypatch.setattr(Path, "exists", lambda _self: False)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.ruff_cmd() is None
    assert calls, "resolver never even tried the module form"


def test_gate_fails_and_prints_the_diagnostics(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod, "ruff_cmd", lambda: ["ruff", "check"])
    monkeypatch.setattr(mod.subprocess, "Popen",
                        lambda *a, **k: _Stub(1, "F401 unused import\n--> tests/x.py:1"))
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "F401" in out and "tests/x.py" in out


def test_silent_failure_is_named_as_a_broken_runner(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod, "ruff_cmd", lambda: ["ruff", "check"])
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: _Stub(1, ""))
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "ПУСТОЙ вывод" in out


def test_clean_run_is_green(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod, "ruff_cmd", lambda: ["ruff", "check"])
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: _Stub(0, "All checks passed"))
    assert mod.main() == 0
    assert "OK" in capsys.readouterr().out


def test_missing_ruff_is_advisory_not_green(monkeypatch, capsys):
    """No tool at all is NOT a pass — it is a stated skip, and it says so."""
    mod = _load()
    monkeypatch.setattr(mod, "ruff_cmd", lambda: None)
    assert mod.main() == 0
    assert "пропуск" in capsys.readouterr().out
    assert sys.platform  # keep the import meaningful for linters
