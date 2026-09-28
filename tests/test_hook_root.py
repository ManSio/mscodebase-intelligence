#!/usr/bin/env python3
"""Pre-commit hook fail-closed guard (2026-09-28).

Regression: when neither `.git` nor `KNOWN_ISSUES.md` markers are found
(renamed tree, copied tree, broken `.git`), the hook must FAIL CLOSED
(exit != 0, explicit "project root not found") — never print 9x
"script not found" + "All pre-commit checks passed" with exit 0.
"""

import importlib.util
import shutil
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / ".githooks" / "pre-commit"


def _load_hook():
    # Extensionless hook file -> SourceFileLoader (spec_from_file_location
    # returns a None-spec with no known loader for such paths).
    loader = SourceFileLoader("hook_under_test", str(HOOK))
    spec = importlib.util.spec_from_loader("hook_under_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_find_project_root_none_in_markerless_tmpdir(tmp_path):
    """find_project_root() returns None when no markers exist above __file__."""
    mod = _load_hook()
    # Simulate hook living in a markerless tree: point __file__ under tmp_path.
    mod.__file__ = str(tmp_path / "hooks" / "pre-commit")
    assert mod.find_project_root() is None


def test_hook_exits_nonzero_in_markerless_tmpdir(tmp_path):
    """Safe repro from the investigation: copied hook must fail closed."""
    work = tmp_path / "copytree"
    work.mkdir()
    copied = work / "pre-commit"
    shutil.copy(HOOK, copied)
    # Sanity: no markers anywhere above the copy inside tmp_path, and the
    # walk must not escape into a real repo — tmp_path itself is markerless.
    assert not (work / ".git").exists()
    assert not (work / "KNOWN_ISSUES.md").exists()
    proc = subprocess.run(
        [sys.executable, str(copied)],
        capture_output=True,
        timeout=120,
        cwd=str(tmp_path),
        # Hook forces utf-8 stdout (emoji); parent must decode the same —
        # default cp1251 on Win loses bytes and yields stdout=None.
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode != 0, f"hook passed fail-open:\n{proc.stdout}"
    assert "All pre-commit checks passed" not in proc.stdout
    assert "project root not found" in proc.stdout


def test_find_project_root_resolves_real_repo():
    """Positive control: in-repo, find_project_root() returns a real Path."""
    mod = _load_hook()
    root = mod.find_project_root()
    assert root is not None
    assert (root / "KNOWN_ISSUES.md").is_file()
