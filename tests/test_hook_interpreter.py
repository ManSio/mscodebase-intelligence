#!/usr/bin/env python3
"""The hook must run gates with the project's interpreter, not git's (P-042).

Git executes `pre-commit` through the shebang (`#!/usr/bin/env python`), which is
the *global* interpreter. On 2026-11-15 gate-zero collected 92 errors on green
code because that interpreter had no `httpx`, so every code commit looked red.

The hand-over also has to carry the verdict: `os.execv` handed over on Windows
by returning to the parent, which exited 0 — the commit went through while the
child printed "❌ Pre-commit checks FAILED" (P-048). Tests below pin both.

These tests pin the resolution order and the fail-open-with-warning path; the
re-exec itself is verified end to end by running the hook with a global python
and reading the `🔧 interpreter:` line (it must name the venv).
"""

import importlib.util
import os
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / ".githooks" / "pre-commit"


def _load_hook():
    loader = SourceFileLoader("hook_interpreter_under_test", str(HOOK))
    spec = importlib.util.spec_from_loader("hook_interpreter_under_test", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _make_venv_python(root: Path, env_dir: str = "venv") -> Path:
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    name = "python.exe" if os.name == "nt" else "python"
    candidate = root / env_dir / bin_dir / name
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("", encoding="utf-8")
    return candidate


def test_venv_python_is_preferred(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCB_PYTHON", raising=False)
    expected = _make_venv_python(tmp_path)
    assert _load_hook().resolve_project_python(tmp_path) == expected


def test_dot_venv_is_the_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCB_PYTHON", raising=False)
    expected = _make_venv_python(tmp_path, env_dir=".venv")
    assert _load_hook().resolve_project_python(tmp_path) == expected


def test_mscb_python_override_wins(tmp_path, monkeypatch):
    preferred = _make_venv_python(tmp_path)
    override = tmp_path / "custom-python"
    override.write_text("", encoding="utf-8")
    monkeypatch.setenv("MSCB_PYTHON", str(override))
    resolved = _load_hook().resolve_project_python(tmp_path)
    assert resolved == override, "an explicit override must win over venv/"
    assert resolved != preferred


def test_missing_venv_returns_none(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCB_PYTHON", raising=False)
    assert _load_hook().resolve_project_python(tmp_path) is None


def test_broken_override_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCB_PYTHON", str(tmp_path / "does-not-exist"))
    assert _load_hook().resolve_project_python(tmp_path) is None, (
        "a wrong override must not silently fall back to another interpreter"
    )


class _Proc:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_reexec_propagates_the_child_verdict(tmp_path, monkeypatch):
    """A failing gate inside the child must fail the commit (P-048).

    `os.execv` handed over on Windows by returning to the parent, so the hook
    exited 0 and git committed while the child printed
    "❌ Pre-commit checks FAILED". Twice on 2026-11-16.
    """
    hook = _load_hook()
    fake = _make_venv_python(tmp_path)
    monkeypatch.delenv("MSCB_HOOK_REEXEC", raising=False)
    monkeypatch.setattr(hook, "resolve_project_python", lambda root: fake)
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["env"] = kwargs.get("env") or {}
        return _Proc(7)

    monkeypatch.setattr(hook, "_RUN", fake_run)
    with pytest.raises(SystemExit) as exc:
        hook.ensure_project_python(tmp_path)
    assert exc.value.code == 7, "the child's exit code must become the hook's"
    assert seen["env"].get("MSCB_HOOK_REEXEC") == "1", "must not re-exec forever"
    assert seen["argv"][0] == str(fake), "the child must run under the venv python"


def test_reexec_happens_once(tmp_path, monkeypatch):
    hook = _load_hook()
    monkeypatch.setenv("MSCB_HOOK_REEXEC", "1")
    called = []
    monkeypatch.setattr(hook, "_RUN", lambda *a, **k: called.append(a))
    assert hook.ensure_project_python(tmp_path) is None
    assert called == [], "the re-executed hook must run the gates itself"


def test_unstartable_interpreter_fails_closed(tmp_path, monkeypatch):
    """No interpreter → no verdict → no commit. Silence is not consent."""
    hook = _load_hook()
    monkeypatch.delenv("MSCB_HOOK_REEXEC", raising=False)
    monkeypatch.setattr(hook, "resolve_project_python", lambda root: _make_venv_python(tmp_path))

    def boom(argv, **kwargs):
        raise OSError("no such binary")

    monkeypatch.setattr(hook, "_RUN", boom)
    with pytest.raises(SystemExit) as exc:
        hook.ensure_project_python(tmp_path)
    assert exc.value.code != 0
