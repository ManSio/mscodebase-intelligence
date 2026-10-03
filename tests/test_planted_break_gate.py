"""Planted-break gate tests — prove guards are alive, not decoration.

Inspired by Tom Jones (dev.to hooks article): "Ours only became trustworthy
once the planted break was run on every release rather than once at build time."

Each test plants a deliberate violation in a temp copy, runs the real guard
logic, and asserts it CATCHES the break. A positive control verifies the guard
does NOT fire on clean input.

Guards tested (from scripts/architecture_linter.py):
  1. _check_core_no_mcp_imports  — core must not import MCP
  2. _check_tools_no_direct_registry — tools must not import Registry/Bridge
  3. _check_stale_references     — no stale name references in code
"""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LINTER = REPO / "scripts" / "architecture_linter.py"
RESULTS_DIR = REPO / "experiments" / "planted_break"
RESULTS_FILE = RESULTS_DIR / "results.json"

_spec = importlib.util.spec_from_file_location("architecture_linter", LINTER)
assert _spec is not None and _spec.loader is not None
linter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(linter)


def _make_temp_repo(tmp_path: Path) -> Path:
    """Create minimal repo structure for linter checks."""
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "src" / "mcp" / "tools").mkdir(parents=True)
    return tmp_path


def _run_check(monkeypatch, tmp_path: Path, check_fn) -> list[str]:
    """Run a linter check against temp repo."""
    monkeypatch.setattr(linter, "REPO", tmp_path)
    return check_fn()


# ─────────────────────────────────────────────────────────────────────────────
# Guard 1: Core must not import MCP
# ─────────────────────────────────────────────────────────────────────────────


def test_core_no_mcp_imports_negative_control(monkeypatch, tmp_path):
    """PLANTED BREAK: core file imports src.mcp — guard MUST catch it."""
    _make_temp_repo(tmp_path)
    bad_file = tmp_path / "src" / "core" / "evil.py"
    bad_file.write_text("from src.mcp.server import something\n", encoding="utf-8")

    errors = _run_check(monkeypatch, tmp_path, linter._check_core_no_mcp_imports)
    caught = len(errors) > 0
    assert caught, "Guard FAILED to catch core→MCP import (decoration!)"
    assert any("evil.py" in e for e in errors), f"Wrong file flagged: {errors}"
    _record_result("core_no_mcp_imports", "negative", True)


def test_core_no_mcp_imports_positive_control(monkeypatch, tmp_path):
    """CLEAN: core file with no MCP imports — guard MUST NOT fire."""
    _make_temp_repo(tmp_path)
    good_file = tmp_path / "src" / "core" / "clean.py"
    good_file.write_text("import os\nfrom pathlib import Path\n", encoding="utf-8")

    errors = _run_check(monkeypatch, tmp_path, linter._check_core_no_mcp_imports)
    passed = errors == []
    assert passed, f"Guard fired on clean input: {errors}"
    _record_result("core_no_mcp_imports", "positive", True)


# ─────────────────────────────────────────────────────────────────────────────
# Guard 2: Tools must not import Registry/Bridge/Passport directly
# ─────────────────────────────────────────────────────────────────────────────


def test_tools_no_direct_registry_negative_control(monkeypatch, tmp_path):
    """PLANTED BREAK: tools file imports Registry directly — guard MUST catch it."""
    _make_temp_repo(tmp_path)
    bad_file = tmp_path / "src" / "mcp" / "tools" / "evil_tool.py"
    bad_file.write_text(
        "from src.core.project_indexer_registry import ProjectIndexerRegistry\n",
        encoding="utf-8",
    )

    errors = _run_check(monkeypatch, tmp_path, linter._check_tools_no_direct_registry)
    caught = len(errors) > 0
    assert caught, "Guard FAILED to catch direct Registry import (decoration!)"
    assert any("evil_tool.py" in e for e in errors), f"Wrong file flagged: {errors}"
    _record_result("tools_no_direct_registry", "negative", True)


def test_tools_no_direct_registry_positive_control(monkeypatch, tmp_path):
    """CLEAN: tools file with no forbidden imports — guard MUST NOT fire."""
    _make_temp_repo(tmp_path)
    good_file = tmp_path / "src" / "mcp" / "tools" / "clean_tool.py"
    good_file.write_text("import sys\nfrom pathlib import Path\n", encoding="utf-8")

    errors = _run_check(monkeypatch, tmp_path, linter._check_tools_no_direct_registry)
    passed = errors == []
    assert passed, f"Guard fired on clean input: {errors}"
    _record_result("tools_no_direct_registry", "positive", True)


# ─────────────────────────────────────────────────────────────────────────────
# Guard 3: No stale name references
# ─────────────────────────────────────────────────────────────────────────────


def test_stale_references_negative_control(monkeypatch, tmp_path):
    """PLANTED BREAK: file contains .codebase_index (stale name) — guard MUST catch it."""
    _make_temp_repo(tmp_path)
    bad_file = tmp_path / "src" / "core" / "stale.py"
    bad_file.write_text(
        "# This uses .codebase_index for storage\n",
        encoding="utf-8",
    )

    errors = _run_check(monkeypatch, tmp_path, linter._check_stale_references)
    caught = len(errors) > 0
    assert caught, "Guard FAILED to catch stale reference (decoration!)"
    assert any("stale.py" in e for e in errors), f"Wrong file flagged: {errors}"
    _record_result("stale_references", "negative", True)


def test_stale_references_positive_control(monkeypatch, tmp_path):
    """CLEAN: file with no stale references — guard MUST NOT fire."""
    _make_temp_repo(tmp_path)
    good_file = tmp_path / "src" / "core" / "modern.py"
    good_file.write_text(
        "# This module uses standard imports only\n",
        encoding="utf-8",
    )

    errors = _run_check(monkeypatch, tmp_path, linter._check_stale_references)
    passed = errors == []
    assert passed, f"Guard fired on clean input: {errors}"
    _record_result("stale_references", "positive", True)


# ─────────────────────────────────────────────────────────────────────────────
# Results recorder — runs once at session end
# ─────────────────────────────────────────────────────────────────────────────


_RESULTS: dict[str, dict] = {}


def _record_result(guard_name: str, control_type: str, passed: bool) -> None:
    """Record a test result into the shared _RESULTS dict."""
    if guard_name not in _RESULTS:
        _RESULTS[guard_name] = {
            "guard_name": guard_name,
            "negative_control_caught": False,
            "positive_control_passed": False,
        }
    if control_type == "negative":
        _RESULTS[guard_name]["negative_control_caught"] = passed
    elif control_type == "positive":
        _RESULTS[guard_name]["positive_control_passed"] = passed


def _record_results(guards_results: dict) -> None:
    """Write results to experiments/planted_break/results.json.

    The write is ATOMIC (temp file + os.replace). A plain write_text is a torn
    write when two xdist workers land here at once, and this file is regenerated
    on every run and read by nobody — so a torn copy is pure noise in git status.
    os.replace is atomic on POSIX and on Windows (same volume), which is why the
    temp file has to sit next to the target rather than in %TEMP%.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "guards": guards_results,
        "all_passed": all(
            g["negative_control_caught"] and g["positive_control_passed"]
            for g in guards_results.values()
        ),
    }
    tmp = RESULTS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, RESULTS_FILE)


@pytest.fixture(scope="session", autouse=True)
def _write_results():
    """After all tests in this file, write results.json."""
    yield
    _record_results(_RESULTS)
