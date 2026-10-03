"""The pre-commit hook must return a verdict for every gate, including a timeout.

Observed 2026-10-03: the hook produced no output at all and had to be bypassed
with `--no-verify`. Two causes, both fixed here:
  1. nothing was printed before a gate ran, so a slow gate looked like a hang;
  2. `proc.communicate(timeout=...)` raised an UNHANDLED TimeoutExpired, so a
     slow gate killed the hook with a traceback and no verdict — which reads
     exactly like "the gate is broken".

The negative control at the bottom runs the pre-fix hook from git and asserts it
raises instead of answering. If that assertion ever stops failing, the test has
stopped testing the fix.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".githooks" / "pre-commit"


def _load_hook(path: Path, timeout: int | None, name: str):
    if timeout is None:
        os.environ.pop("MSCB_PRECOMMIT_GATE_TIMEOUT", None)
    else:
        os.environ["MSCB_PRECOMMIT_GATE_TIMEOUT"] = str(timeout)
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, str(path)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gate(tmp_path: Path, body: str) -> str:
    p = tmp_path / "gate.py"
    p.write_text(body, encoding="utf-8")
    return str(p)  # absolute: `project_root / absolute` == absolute


def test_gate_that_passes(tmp_path):
    mod = _load_hook(HOOK, 60, "hook_pass")
    assert mod.run_script(_gate(tmp_path, "print('ok')"), "g") is True


def test_gate_that_fails(tmp_path):
    mod = _load_hook(HOOK, 60, "hook_fail")
    assert mod.run_script(_gate(tmp_path, "raise SystemExit(1)"), "g") is False


def test_missing_gate_is_skipped_not_failed(tmp_path):
    mod = _load_hook(HOOK, 60, "hook_missing")
    assert mod.run_script(str(tmp_path / "nope.py"), "g") is True


def test_timeout_returns_a_verdict_instead_of_raising(tmp_path, capsys):
    mod = _load_hook(HOOK, 2, "hook_timeout")
    slow = _gate(tmp_path, "import time; time.sleep(60)")
    assert mod.run_script(slow, "slowgate") is False
    out = capsys.readouterr().out
    assert "TIMEOUT" in out and "slowgate" in out
    assert "Traceback" not in out


def test_running_line_is_printed_before_the_gate_finishes(tmp_path, capsys):
    """The reason the hook looked dead: nothing was printed until the end."""
    mod = _load_hook(HOOK, 60, "hook_progress")
    mod.run_script(_gate(tmp_path, "print('ok')"), "progressgate")
    out = capsys.readouterr().out
    assert out.index("progressgate") < out.index("OK")


def test_gate_budget_is_configurable():
    """Without the env override the timeout path could not be tested at all."""
    mod = _load_hook(HOOK, 7, "hook_budget")
    assert mod.GATE_TIMEOUT == 7
    os.environ.pop("MSCB_PRECOMMIT_GATE_TIMEOUT", None)
    mod2 = _load_hook(HOOK, None, "hook_budget_default")
    assert mod2.GATE_TIMEOUT == 900


class _FakeProc:
    """communicate() times out once, exactly like a gate that never answers."""

    def __init__(self):
        self.returncode = None
        self.killed = False
        self._raised = False

    def communicate(self, timeout=None):
        if not self._raised:
            self._raised = True
            raise subprocess.TimeoutExpired(cmd="gate", timeout=timeout)
        return "", None

    def kill(self):
        self.killed = True


def _old_run_script(script_path, label, _Popen=None):
    """The pre-fix hook body, verbatim in behaviour.

    Kept inline on purpose. Two earlier versions of this control were worse:
    one copied the old hook into the repo (tripped
    `test_no_tracked_file_mutation`), the other read it back with `git show HEAD`
    — which silently stopped being a control the moment the fix was committed.
    """
    proc = (_Popen or subprocess.Popen)(
        [sys.executable, script_path],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        encoding="utf-8", errors="replace",
    )
    stdout, _ = proc.communicate(timeout=900)   # no try/except — that was the bug
    if proc.returncode != 0:
        print(f"  ❌ {label}: exit {proc.returncode}")
        if stdout:
            for line in stdout.splitlines()[-10:]:
                print(f"    {line}")
        return False
    print(f"  ✅ {label}: OK")
    return True


def test_prefix_hook_could_not_answer_a_timeout(tmp_path):
    """NEGATIVE CONTROL: the pre-fix hook had no verdict for a slow gate."""
    gate = _gate(tmp_path, "pass")
    with pytest.raises(subprocess.TimeoutExpired):
        _old_run_script(gate, "slowgate", _Popen=lambda *a, **k: _FakeProc())


def test_fixed_hook_answers_the_same_timeout(tmp_path, capsys):
    mod = _load_hook(HOOK, 2, "hook_fixed_timeout")
    proc = _FakeProc()
    mod.subprocess.Popen = lambda *a, **k: proc
    assert mod.run_script(_gate(tmp_path, "pass"), "slowgate") is False
    assert proc.killed, "the hung gate process was not killed"
    out = capsys.readouterr().out
    assert "TIMEOUT" in out and "slowgate" in out
    assert "Traceback" not in out
