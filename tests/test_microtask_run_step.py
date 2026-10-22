"""Tests for the tool-shaped sidecar (run_step.py): the apply path and the guards.

The apply path needs no model: the parent already specified the edit, the
harness applies it deterministically and verifies it. That is the architect /
editor split with the editor doing nothing but formatting.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT / "tools" / "microtask_pipeline"
RUN_STEP = PIPELINE_DIR / "run_step.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PIPELINE_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


run_step = _load("run_step")


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "repo"
    (project / "src").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "src" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (project / "tests" / "test_mod.py").write_text(
        "from src.mod import f\n\n\ndef test_f():\n    assert f() == 2\n", encoding="utf-8"
    )
    return project


def _call(project: Path, args: dict) -> subprocess.CompletedProcess:
    payload = {
        "tool": "edit",
        "args": args,
        "directory": str(project),
        "worktree": str(project),
    }
    return subprocess.run(
        [sys.executable, str(RUN_STEP), json.dumps(payload)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )


def test_apply_mode_edits_and_verifies(tmp_path):
    project = _project(tmp_path)
    result = _call(
        project,
        {
            "filePath": str(project / "src" / "mod.py"),
            "oldString": "return 1",
            "newString": "return 2",
            "acceptance": "python -m pytest tests/test_mod.py -q",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (project / "src" / "mod.py").read_text(encoding="utf-8") == "def f():\n    return 2\n"
    assert "exit 0" in result.stdout
    assert "receipt r-" in result.stdout


def test_apply_mode_reports_a_failing_acceptance(tmp_path):
    project = _project(tmp_path)
    result = _call(
        project,
        {
            "filePath": str(project / "src" / "mod.py"),
            "oldString": "return 1",
            "newString": "return 3",
            "acceptance": "python -m pytest tests/test_mod.py -q",
        },
    )
    assert result.returncode == 1
    assert "exit 1" in result.stdout
    # the change was still applied — the receipt reports the truth
    assert "return 3" in (project / "src" / "mod.py").read_text(encoding="utf-8")


def test_test_files_are_refused(tmp_path):
    project = _project(tmp_path)
    result = _call(
        project,
        {
            "filePath": str(project / "tests" / "test_mod.py"),
            "oldString": "assert f() == 2",
            "newString": "assert True",
            "acceptance": "python -m pytest tests/test_mod.py -q",
        },
    )
    assert result.returncode == 1
    assert "refused" in result.stdout
    assert "assert f() == 2" in (project / "tests" / "test_mod.py").read_text(encoding="utf-8")


def test_old_string_not_found_is_reported(tmp_path):
    project = _project(tmp_path)
    result = _call(
        project,
        {
            "filePath": str(project / "src" / "mod.py"),
            "oldString": "this is not in the file",
            "newString": "return 2",
            "acceptance": "",
        },
    )
    assert result.returncode == 1
    assert "not found" in result.stdout or "could not produce" in result.stdout


def test_replacement_tolerates_reindentation(tmp_path):
    project = _project(tmp_path)
    result = _call(
        project,
        {
            "filePath": str(project / "src" / "mod.py"),
            "oldString": "        return 1",
            "newString": "        return 2",
            "acceptance": "",
        },
    )
    # the file uses 4-space indentation: the matcher still finds the snippet
    assert result.returncode == 0, result.stdout + result.stderr
    assert "return 2" in (project / "src" / "mod.py").read_text(encoding="utf-8")
    # and the same tolerance in the unit
    patched, error = run_step.apply_replacement("def f():\n    return 1\n", "        return 1", "    return 2\n")
    assert error == ""
    assert patched == "def f():\n    return 2\n"
