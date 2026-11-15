#!/usr/bin/env python3
"""The hook must run gates with the project's interpreter, not git's (P-042).

Git executes `pre-commit` through the shebang (`#!/usr/bin/env python`), which is
the *global* interpreter. On 2026-11-15 gate-zero collected 92 errors on green
code because that interpreter had no `httpx`, so every code commit looked red.

These tests pin the resolution order and the fail-open-with-warning path; the
re-exec itself is verified end to end by running the hook with a global python
and reading the `🔧 interpreter:` line (it must name the venv).
"""

import importlib.util
import os
from importlib.machinery import SourceFileLoader
from pathlib import Path

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
