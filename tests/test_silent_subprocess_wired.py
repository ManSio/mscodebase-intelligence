#!/usr/bin/env python3
"""Liveness: silent_subprocess is wired into the entry point (2026-09-29).

PR #56 shipped src/core/silent_subprocess.py INERT — nothing imported it.
fix/redteam-tails wires it into src/main.py (import + apply() at startup).

Proves liveness in a FRESH interpreter (no conftest Popen-shim at import
time — the autouse _no_console_windows fixture replaces Popen with a plain
function, which would mask the real startup path): the child imports
src.main as the server would, then asserts the guard is applied — and on
win32 that subprocess.Popen is the silent wrapper.
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_CHILD = (
    "import subprocess, sys; "
    "import src.main; "
    "import src.core.silent_subprocess as mod; "
    "assert 'src.core.silent_subprocess' in sys.modules, 'not wired'; "
    "assert mod._APPLIED is True, 'not applied'; "
    "print('WIRED_OK'); "
    "print('POPEN=' + type(subprocess.Popen).__name__ + ':' + subprocess.Popen.__name__)"
)


def test_entry_point_wires_silent_subprocess_fresh_process():
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"child startup import failed:\n{proc.stderr[-2000:]}"
    assert "WIRED_OK" in proc.stdout, f"guard not applied after startup import:\n{proc.stdout}"
    if sys.platform == "win32":
        assert "_SilentPopen" in proc.stdout, (
            f"Popen is not the silent wrapper after startup import:\n{proc.stdout}"
        )
