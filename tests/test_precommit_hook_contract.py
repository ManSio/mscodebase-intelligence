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


def _old_hook_module():
    """Load the committed (pre-fix) hook. Returns (module, holder_path)."""
    holder = ROOT / "build" / f"hook-negative-control-{os.getpid()}"
    holder.parent.mkdir(parents=True, exist_ok=True)
    # P-14 live: the old hook is full of Cyrillic, and `text=True` would decode
    # git's UTF-8 output through the cp1251 console codepage.
    src = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:.githooks/pre-commit"],
                         capture_output=True, encoding="utf-8", errors="replace",
                         timeout=60)
    assert src.returncode == 0, src.stderr
    holder.write_text(src.stdout, encoding="utf-8")
    mod = _load_hook(holder, None, "hook_prefix")
    assert mod.find_project_root() == ROOT
    return mod, holder


def test_prefix_hook_raises_on_timeout_negative_control(tmp_path):
    """NEGATIVE CONTROL: the pre-fix hook could not answer a timeout at all.

    Driven by a fake Popen rather than a real sleep, because the pre-fix hook
    hardcodes its 900s budget and ignores the env override — a real sleep would
    only prove that 60 < 900.
    """
    mod, holder = _old_hook_module()
    try:
        mod.subprocess.Popen = lambda *a, **k: _FakeProc()
        with pytest.raises(subprocess.TimeoutExpired):
            mod.run_script(_gate(tmp_path, "pass"), "slowgate")
    finally:
        holder.unlink(missing_ok=True)
    assert not holder.exists(), "temp copy of the old hook left behind"
