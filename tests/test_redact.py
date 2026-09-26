"""Planted-key test for scripts/redact.py — proves redaction is alive.

Negative control: planted personal path/username MUST be scrubbed.
Positive control: clean text MUST pass through unchanged.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "redact.py"


def _run_redact(text: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=text, capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert proc.returncode == 0, f"redact failed: {proc.stderr}"
    return proc.stdout


def test_drive_path_is_redacted() -> None:
    out = _run_redact(r"Path: D:\Project\MSCodeBase\src\core")
    assert "<project>" in out
    assert "D:" not in out


def test_forward_slash_path_is_redacted() -> None:
    out = _run_redact("Path: D:/Project/MSCodeBase/src/core")
    assert "<project>" in out
    assert "D:" not in out


def test_username_is_redacted() -> None:
    out = _run_redact("Owner: misha confirmed")
    assert "<user>" in out
    assert "misha" not in out


def test_clean_text_unchanged() -> None:
    clean = "This is a clean sentence with no personal data."
    out = _run_redact(clean)
    assert out.strip() == clean


def test_selftest_passes() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert proc.returncode == 0
    assert "selftest PASS" in proc.stdout
